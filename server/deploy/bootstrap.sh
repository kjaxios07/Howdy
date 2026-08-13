#!/usr/bin/env bash
# Howdy — one-shot VPS bootstrap for Ubuntu 24.04.
#
#   curl -fsSL https://raw.githubusercontent.com/<you>/Howdy/main/server/deploy/bootstrap.sh | sudo bash
#
# Idempotent: safe to re-run.

set -euo pipefail

APP_USER="howdy"
SECRETS_DIR="/etc/howdy/secrets"

log() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root."; exit 1; }

log "System packages"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades age

log "Automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

log "Firewall (deny inbound, allow 22/80/443)"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'ssh'
ufw allow 80/tcp comment 'http'
ufw allow 443/tcp comment 'https'
ufw allow 443/udp comment 'http3'
ufw --force enable

log "SSH hardening"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd

log "fail2ban"
systemctl enable --now fail2ban

log "Docker"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

log "Application user"
id -u "$APP_USER" &>/dev/null || useradd -m -s /bin/bash "$APP_USER"
usermod -aG docker "$APP_USER"

log "Secrets"
mkdir -p "$SECRETS_DIR"
chmod 700 /etc/howdy "$SECRETS_DIR"

gen_secret() {  # $1 = filename, $2 = byte length
  local f="$SECRETS_DIR/$1"
  if [[ ! -s "$f" ]]; then
    openssl rand -base64 "$2" | tr -d '\n' > "$f"
    echo "  generated $1"
  else
    echo "  kept existing $1"
  fi
  chmod 400 "$f"; chown root:root "$f"
}
gen_secret kek_v1 32          # AES-256 master key
gen_secret pepper 32          # HMAC pepper for lookup hashes
gen_secret cookie_secret 32

for manual in anthropic_key google_client_secret; do
  f="$SECRETS_DIR/$manual"
  [[ -s "$f" ]] || { touch "$f"; echo "  ⚠  $manual is EMPTY — paste the value in before starting"; }
  chmod 400 "$f"; chown root:root "$f"
done

log "Swap (small boxes OOM without it)"
if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

cat <<'EOF'

──────────────────────────────────────────────────────────────
 Bootstrap complete.

 Still to do, by hand:
   1. echo -n 'sk-ant-...'  > /etc/howdy/secrets/anthropic_key
   2. echo -n 'GOCSPX-...'  > /etc/howdy/secrets/google_client_secret
   3. chmod 400 /etc/howdy/secrets/*
   4. Point your domain's A/AAAA record at this server
   5. cd /home/howdy/Howdy/server && cp .env.example .env  (set DOMAIN, DB_PASSWORD,
      GOOGLE_CLIENT_ID)
   6. docker compose up -d

 BACK UP /etc/howdy/secrets/kek_v1 SOMEWHERE OFFLINE.
 Lose it and every stored conversation is permanently unreadable.
──────────────────────────────────────────────────────────────
EOF
