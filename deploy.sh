#!/usr/bin/env bash
#
#  Howdy — one-command deploy.
#
#      sudo ./deploy.sh
#
#  Reads howdy.config.json, hardens the box, installs Docker, generates every
#  secret, writes the environment, brings the stack up and verifies it answers.
#
#  Idempotent: safe to run again after editing howdy.config.json.
#  Tested target: fresh Ubuntu 24.04 (x86 or ARM) — including the Oracle Cloud
#  free tier, which is the cheapest place to run this at $0/month.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$REPO_DIR/howdy.config.json"
SECRETS_DIR="/etc/howdy/secrets"
COMPOSE_DIR="$REPO_DIR/server"

bold()  { printf '\n\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()    { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\n\033[1;31m✗ %s\033[0m\n\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo ./deploy.sh"
[[ -f "$CONFIG" ]] || die "howdy.config.json not found next to this script."

# ──────────────────────────────────────────────────────────────────────
bold "Reading howdy.config.json"

command -v python3 >/dev/null || { apt-get update -qq && apt-get install -y -qq python3; }

read_cfg() { python3 -c "
import json,sys
d=json.load(open('$CONFIG'))
for k in '$1'.split('.'): d=d[k]
print(d)
"; }

DOMAIN=$(read_cfg app.domain)
ADMIN_EMAIL=$(read_cfg app.admin_email)
MODEL=$(read_cfg model.id)
PROFILE=$(read_cfg hosting.profile)

[[ "$DOMAIN" == "CHANGE-ME.au" ]] && die "Set app.domain in howdy.config.json first."

ok "Domain   : $DOMAIN"
ok "Model    : $MODEL"
ok "Profile  : $PROFILE"

# ──────────────────────────────────────────────────────────────────────
bold "Hardening the host"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades jq >/dev/null
ok "Base packages"

ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming  >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp  comment 'ssh'   >/dev/null
ufw allow 80/tcp  comment 'http'  >/dev/null
ufw allow 443/tcp comment 'https' >/dev/null
ufw allow 443/udp comment 'http3' >/dev/null
ufw --force enable >/dev/null
ok "Firewall: 22, 80, 443 only"

sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
ok "SSH: keys only"

systemctl enable --now fail2ban >/dev/null 2>&1
ok "fail2ban"

# Small boxes OOM during Docker builds without swap.
if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "2 GB swap"
else
  ok "Swap already present"
fi

# Oracle Cloud images ship with a restrictive iptables policy that silently
# blocks 80/443 even when ufw says they're open. This is the #1 reason a free
# tier deploy appears to hang.
if iptables -L INPUT -n 2>/dev/null | grep -q 'REJECT.*reject-with icmp-host-prohibited'; then
  iptables -I INPUT 4 -p tcp --dport 80  -j ACCEPT 2>/dev/null || true
  iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
  command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
  warn "Oracle-style iptables detected — opened 80/443 explicitly"
fi

# ──────────────────────────────────────────────────────────────────────
bold "Docker"

if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  ok "Installed"
else
  ok "Already installed"
fi
systemctl enable --now docker >/dev/null 2>&1

# ──────────────────────────────────────────────────────────────────────
bold "Secrets"

mkdir -p "$SECRETS_DIR"
chmod 700 /etc/howdy "$SECRETS_DIR"

gen() {
  local f="$SECRETS_DIR/$1"
  if [[ ! -s "$f" ]]; then
    openssl rand -base64 "$2" | tr -d '\n' > "$f"
    ok "generated $1"
  else
    ok "kept existing $1"
  fi
  chmod 400 "$f"; chown root:root "$f"
}

gen kek_v1 32          # AES-256 master key — wraps every user's data key
gen pepper 32          # HMAC pepper for lookup hashes
gen cookie_secret 32

# The two we cannot generate.
ask_secret() {
  local name="$1" prompt="$2" f="$SECRETS_DIR/$1"
  if [[ -s "$f" ]]; then ok "kept existing $name"; return; fi
  if [[ -t 0 ]]; then
    printf '  %s: ' "$prompt"
    read -rs value; echo
    [[ -n "$value" ]] || die "$name cannot be empty."
    printf '%s' "$value" > "$f"
    ok "stored $name"
  else
    touch "$f"
    warn "$name is EMPTY — write it before starting: echo -n '...' > $f"
  fi
  chmod 400 "$f"; chown root:root "$f"
}

ask_secret anthropic_key        "Anthropic API key (sk-ant-...)"
ask_secret google_client_secret "Google OAuth client secret (blank ok for now — press enter)" || true

# Postgres password lives in .env because Compose needs it at container start.
if [[ ! -f "$COMPOSE_DIR/.env" ]] || ! grep -q '^DB_PASSWORD=.\+' "$COMPOSE_DIR/.env" 2>/dev/null; then
  DB_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
else
  DB_PASSWORD=$(grep '^DB_PASSWORD=' "$COMPOSE_DIR/.env" | cut -d= -f2-)
fi

GOOGLE_CLIENT_ID=$(grep '^GOOGLE_CLIENT_ID=' "$COMPOSE_DIR/.env" 2>/dev/null | cut -d= -f2- || true)

cat > "$COMPOSE_DIR/.env" <<EOF
# Generated by deploy.sh from howdy.config.json — do not commit.
DOMAIN=$DOMAIN
ADMIN_EMAIL=$ADMIN_EMAIL
DB_PASSWORD=$DB_PASSWORD
KIP_MODEL=$MODEL
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
EOF
chmod 600 "$COMPOSE_DIR/.env"
ok "wrote server/.env"

# The app reads the config at runtime; put it where the container can see it.
cp "$CONFIG" /etc/howdy/howdy.config.json
chmod 644 /etc/howdy/howdy.config.json
ok "published config to /etc/howdy/"

# ──────────────────────────────────────────────────────────────────────
bold "Building and starting"

cd "$COMPOSE_DIR"
docker compose build --quiet
docker compose up -d
ok "stack up"

# ──────────────────────────────────────────────────────────────────────
bold "Verifying"

printf '  waiting for health'
for i in $(seq 1 40); do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1 \
  || docker compose exec -T app python -c "
import urllib.request,sys
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)
" 2>/dev/null; then
    echo; ok "app is answering"
    break
  fi
  printf '.'; sleep 3
  [[ $i -eq 40 ]] && { echo; warn "app did not become healthy — check: docker compose logs app"; }
done

# Confirm the datastores are NOT reachable from outside. Docker bypasses ufw,
# so this is the check that actually matters.
bold "Exposure check"
for port in 5432 6379; do
  if ss -ltn 2>/dev/null | grep -qE "0\.0\.0\.0:$port|\[::\]:$port"; then
    warn "PORT $port IS LISTENING ON ALL INTERFACES — fix the ports: line in docker-compose.yml"
  else
    ok "port $port is loopback-only"
  fi
done

# ──────────────────────────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────────────────────────
 Howdy is running.

   https://$DOMAIN            (once DNS points here — TLS is automatic)
   https://$DOMAIN/chat

 Still to do:
   • Point an A record for $DOMAIN at this server's public IP
   • Google sign-in: create an OAuth client at
     https://console.cloud.google.com/apis/credentials
     Authorised redirect URI:  https://$DOMAIN/api/auth/callback
     Then:  echo 'GOOGLE_CLIENT_ID=...' >> server/.env
            echo -n 'GOCSPX-...' > $SECRETS_DIR/google_client_secret
            docker compose up -d

 ⚠  BACK UP $SECRETS_DIR/kek_v1 SOMEWHERE OFFLINE.
    Lose it and every stored conversation is permanently unreadable.

 Useful:
   docker compose logs -f app      # tail the app
   docker compose restart app      # after editing howdy.config.json
   docker compose down             # stop everything
────────────────────────────────────────────────────────────────

EOF
