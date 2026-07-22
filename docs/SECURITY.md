# Security model

Howdy serves vulnerable users — newcomers who may not recognise scams, who hold sensitive documents (passports, visas, TFNs), and whose visa status can be harmed by bad information. The security posture follows from that.

## Principles

1. **User text is untrusted input.** It is sanitised before entering the model context and never logged or stored.
2. **The model is untrusted output.** Every reply is post-processed by deterministic server code before the user sees it.
3. **No PII, anywhere.** Not accepted, not stored, not logged.
4. **Fail closed.** If verification can't confirm a link, the link is removed.

## Threat model & mitigations

| Threat | Mitigation | Where |
|---|---|---|
| Hallucinated facts / fake official links | Model restricted to a curated knowledge base; server strips any URL not on the official-domain allowlist | `lib/prompt.js`, `lib/sources.js` |
| Fake rental listings | Kip never quotes listings; it builds search URLs on realestate.com.au / domain.com.au / flatmates.com.au only | `lib/sources.js`, prompt rule 3 |
| Users pasting TFN / passport / card numbers | Regex PII guard refuses the message before any model call | `lib/security.js` |
| Prompt injection ("ignore your instructions…") | Pattern guard + in-prompt defence rule; system prompt never revealed | `lib/security.js`, prompt rule 6 |
| XSS via model output | Frontend HTML-escapes all model text before applying minimal markdown; CSP blocks inline-injected external scripts; `X-Content-Type-Options`, `frame-ancestors 'none'` | `chat.html`, `Vercel.json` |
| Abuse / cost attacks | Per-IP rate limit (20/min), 800-char message cap, 32 KB body cap, 8-turn history cap, `max_tokens` 700 | `lib/config.js`, `lib/security.js` |
| Data breach exposure | Nothing to breach: no database, no session store, no message logging (error logs record error class only) | `api/chat.js` |
| API key leakage | Key lives only in the serverless environment variable; never sent to the client | `api/chat.js` |
| Clickjacking / MIME sniffing / downgrade | `X-Frame-Options: DENY`, `nosniff`, HSTS preload | `Vercel.json` |

## What we deliberately do NOT do

- No accounts, no cookies, no analytics beacons in the MVP — the chat works anonymously.
- No storage of conversations. History lives only in the browser tab and is capped at 8 turns when sent for context.
- No scraping of listing sites — we link to their own search pages instead.

## Known limitations / production hardening

- **Rate limiting is in-memory** per serverless instance. At scale, move to Upstash Redis / Vercel KV.
- **PII regexes are heuristics.** They catch common formats, not every possible identifier. The system prompt adds a second layer (rule 4).
- **CSP allows `'unsafe-inline'` scripts** because the pages are single-file. Moving JS to external files with hashes would tighten this.
- Consider adding CAPTCHA (e.g. Turnstile) on `/api/chat` if abuse appears.

## Testing

`npm test` covers the security-critical paths: sanitisation, PII detection, injection detection, allowlist behaviour (including look-alike domains such as `realestate.com.au.phish.io`), link stripping, and the knowledge-base source_url invariant.
