# Getting kipchat.com.au live

In order. Each step is checkable, and the last one tells you whether it
worked rather than leaving you to guess.

Total: about 90 minutes of actual work, most of it waiting for DNS.

---

## 1. The server — 15 min

**Sydney, not the free tier.** `howdy.config.json` is set to the `launch`
profile for a reason: where student data physically sits is the first thing a
university procurement office asks, and answering "Sydney" beats answering
with an explanation. Moving a live database between regions later is far
worse than $24 a month now.

Any of Vultr / DigitalOcean / Linode, **Sydney region**, Ubuntu 24.04,
2 vCPU / 4 GB. Take the IPv4 address it gives you.

Open ports 22, 80 and 443. Nothing else — Postgres and Redis stay on the
Docker network and must never be reachable from outside.

## 2. DNS — 5 min, then up to an hour of waiting

At your registrar, two A records pointing at the server's IP:

| Type | Name | Value |
|---|---|---|
| A | `@` | your.server.ip |
| A | `www` | your.server.ip |

Then wait. Check with `dig kipchat.com.au +short` — when that returns your IP,
move on. **Do not run the deploy before this resolves**: Caddy will try to get
a certificate, fail, and Let's Encrypt rate-limits repeated failures.

## 3. Google sign-in — 10 min

console.cloud.google.com → new project → OAuth consent screen → Credentials →
OAuth client ID (Web application).

**Authorised redirect URI — exactly this, nothing else:**

```
https://kipchat.com.au/api/auth/callback
```

Google matches that string literally. A trailing slash, a missing `s`, `www`
where there is none — any of them and sign-in dies after the consent screen
with an error a student cannot act on. This is the single most common
first-deploy failure.

Keep the client ID and secret. The deploy asks for them.

## 4. Deploy — 20 min

```bash
git clone https://github.com/kjaxios07/Howdy.git
cd Howdy
sudo ./deploy.sh
```

It hardens the box, installs Docker, generates every secret, writes the
environment, brings the stack up and waits for health. It is idempotent —
safe to run again after editing config.

Have ready: your Anthropic API key, the Google client ID and secret.

## 5. Prove it works — 5 min

This is the step people skip. `deploy.sh` ending cleanly tells you the
process started, not that a student can get an answer.

```bash
cd /path/to/Howdy/server

python3 -m app.preflight --live          # config, TLS, headers, endpoints
python3 -m app.preflight --live --model  # ...and one real model call
```

Exit code 0 means nothing is broken. Every failure names what a student
would experience, so you can tell a real problem from a cosmetic one.

Then, by hand, because some things only a person notices:

- [ ] `https://kipchat.com.au` loads, and `http://` redirects to it
- [ ] Ask Kip something real — *"How do I apply for a TFN?"* — and check
      the answer arrives **with sources under it**
- [ ] Ask something that needs a live figure — *"What is the minimum wage?"*
      — and confirm it searched
- [ ] Sign in with Google end to end, then sign out
- [ ] Ask something in incognito mode and confirm nothing was saved
- [ ] Open it on a phone
- [ ] Ask a safety question and check the crisis numbers appear first

## 6. Watch the first day

```bash
python3 -m app.costs report      # what answers actually cost
python3 -m app.library           # stored answers, and what is still draft
python3 -m app.recheck           # what is due another look
curl https://kipchat.com.au/api/budget
```

The spend ceiling is $40/month and $2.50/day. It degrades in stages rather
than switching off, and safety topics are never degraded — but check the
first day's spend against the estimate anyway, because the estimate has
never met real students.

---

## Before you tell anyone about it

Two things are genuinely not ready, and both are content rather than code.

**The 21 risk-tiered answers are drafts.** Nine crisis, twelve refer. They
are written and tested but nobody has signed them off, so they are invisible
at runtime and those questions go to the model. Get a MARA-registered agent
to read the twelve migration answers and someone from a student support
service to read the nine crisis ones, then:

```bash
python3 -m app.library review safety-005 "Their Name, their role"
```

**A privacy policy and terms, reviewed by an Australian lawyer.** You are
handling conversations about visas, money and personal safety from people
who are not citizens. This is not optional and it is not a template job.

## The order I would actually do things in

1. Deploy and get it working (steps 1–5)
2. Use it yourself for a week — you will find things no test does
3. Ten real students, watch them use it, say nothing while they do
4. Get the 21 answers reviewed
5. Privacy policy and terms
6. Then tell people

Steps 2 and 3 are where the product gets good. Everything before them is
just making it exist.
