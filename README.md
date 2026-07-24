# Howdy 🐨

**A verified-source companion for international students and new migrants in Australia.**

Kip (our sunny little mate in a bush hat) answers everyday questions — visas, work rights, tax, housing, health, banking — grounded in official Australian government sources. Every reply is source-verified server-side before the user sees it.

> Guidance, not legal advice. A companion, not a lawyer.

## Why this exists

Moving to Australia means navigating Home Affairs, the ATO, Fair Work, OSHC, rental bonds and state transport systems — usually in your second language, usually alone. Bad information costs students real money and sometimes their visa. Howdy exists so they can live their Aussie life effortlessly, obey the rules, and stay safe.

## Architecture

```
Index.html            Landing page (module-first, static)
chat.html             Chat UI (safe rendering, verified-sources panel)

api/chat.js           POST /api/chat — the only model endpoint
api/health.js         GET  /health  — service + knowledge base status
api/subscribe.js      POST /api/subscribe — waitlist (no PII stored)

lib/config.js         All tunables in one place
lib/security.js       Rate limit · input sanitising · PII guard · injection guard
lib/sources.js        Official-domain allowlist · reply verification · listing-link builder
lib/modules.js        The 10 student-facing modules
lib/prompt.js         Kip's system prompt (built from modules + knowledge base)

knowledge/base.json   Verified facts, organised by module, source_url on every section
scripts/              Daily knowledge refresh (GitHub Actions)
test/run-tests.js     Dependency-free tests for the security-critical paths
docs/                 SECURITY.md (threat model) · PRODUCT.md (analysis)
```

### The request pipeline

Every chat message passes through, in order:

1. **Security headers** on the response
2. **Rate limit** — 20 requests/min per IP
3. **Body validation** — size cap, type checks, length caps
4. **PII guard** — messages containing TFN/passport/card/phone/email patterns are refused *before* they reach the model
5. **Injection guard** — prompt-injection patterns get a canned redirect
6. **Claude** — answers only from the verified knowledge base (prompt-cached)
7. **Source verification** — deterministic server code strips any URL not on the official allowlist and returns the verified list to the UI

Step 7 is the heart of the product: the model *claims* sources, the server *proves* them.

### Housing searches

Kip never invents listings. "Two bedroom house near Acacia Ridge 4110 Brisbane" produces direct search links to live results:

- `realestate.com.au/rent/property-house-with-2-bedrooms-in-acacia+ridge,+qld,+4110/list-1`
- `domain.com.au/rent/acacia-ridge-qld-4110/?bedrooms=2`
- `flatmates.com.au/rooms/acacia-ridge-4110`

## Running locally

```bash
npm install
export ANTHROPIC_API_KEY=sk-ant-...
npx vercel dev          # or deploy: npx vercel
npm test                # security/source-verification test suite
```

Optional env vars: `KIP_MODEL` (defaults to `claude-opus-4-8`; set `claude-sonnet-5` for lower cost per message).

## Updating knowledge

`knowledge/base.json` is the single source of truth for facts. Every section must carry a `source_url` pointing at the official page it came from — `npm test` enforces this. The GitHub Actions workflow refreshes it daily.

## Disclaimers shown to users

- Kip gives **general information from official sources** — not legal, migration, tax or financial advice.
- Visa decisions → MARA-registered agents ([mara.gov.au](https://www.mara.gov.au))
- Legal issues → university student legal services
- Money decisions → [moneysmart.gov.au](https://moneysmart.gov.au)
