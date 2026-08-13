# Howdy — Python backend

FastAPI + PostgreSQL + Valkey, deployed to a single VPS with Docker Compose.
Google sign-in, saved chat history, per-user envelope encryption.

## Quick start (local)

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Dev secrets (throwaway)
export HOWDY_KEK=$(openssl rand -base64 32)
export HOWDY_PEPPER=$(openssl rand -base64 32)
export HOWDY_COOKIE_SECRET=$(openssl rand -base64 32)
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_CLIENT_SECRET=...
export HOWDY_ENV=development

uvicorn app.main:app --reload
# API docs at http://localhost:8000/api/docs (development only)
```

## Deploy to a VPS

```bash
# 1. On a fresh Ubuntu 24.04 box, as root:
curl -fsSL .../server/deploy/bootstrap.sh | bash

# 2. Paste the two manual secrets
echo -n 'sk-ant-...' > /etc/howdy/secrets/anthropic_key
echo -n 'GOCSPX-...' > /etc/howdy/secrets/google_client_secret
chmod 400 /etc/howdy/secrets/*

# 3. Configure and start
git clone <repo> /home/howdy/Howdy && cd /home/howdy/Howdy/server
cp .env.example .env && $EDITOR .env
docker compose up -d

# 4. Verify nothing internal is exposed (run from ANOTHER machine)
nmap -Pn -p 22,80,443,5432,6379 your-server-ip
# 5432 and 6379 must show as filtered/closed
```

> ⚠️ **Back up `/etc/howdy/secrets/kek_v1` somewhere offline.** Lose it and every
> stored conversation is permanently unreadable — that is the design working as
> intended, but it applies to you too.

## Layout

```
app/
  config.py        Settings; secrets read from files, not env vars
  crypto.py        Envelope encryption (KEK → per-user DEK → content)
  models.py        SQLAlchemy models
  security.py      PII guard, injection guard, sanitisation (pure, no deps)
  ratelimit.py     Sliding-window limiter, IP hashing (needs Redis)
  sessions.py      Opaque server-side sessions
  sources.py       Official-domain allowlist + reply verification
  prompt.py        Kip's system prompt (prompt-cached)
  retention.py     Nightly expiry sweep
  routers/
    auth.py            Google OIDC + PKCE
    chat.py            The only route that calls the model
    conversations.py   History CRUD (ownership in every predicate)
    me.py              Export, retention, account deletion
deploy/
  bootstrap.sh     VPS hardening + Docker + secret generation
  backup.sh        Nightly age-encrypted dump
tests/
  test_security.py 34 tests over the security-critical paths
```

## Tests

```bash
python -m pytest tests -q
```

Covers: PII detection, injection detection, the domain allowlist (including
suffix-confusion attacks like `realestate.com.au.phish.io`), AES-GCM round
trips, AAD row-binding, DEK wrapping, and nonce uniqueness.

## Storage modes

| Mode | Written to the database |
|---|---|
| Guest (signed out) | Nothing |
| Incognito (signed in, toggled) | Nothing |
| Saved (default, signed in) | Encrypted with the user's own key |
