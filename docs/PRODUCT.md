# Product analysis — the best output Howdy can give students & migrants, securely

*Why we built this: so international students and new migrants can live an Aussie life effortlessly, obey the rules, and stay safe — with a companion, not a lawyer.*

## 1. What students actually need (and in what order)

Talking to the journey chronologically, the need stack looks like this:

| Phase | Burning questions | Kip module |
|---|---|---|
| Pre-arrival → week 1 | "What do I do first? SIM, bank, OSHC, address rules" | 🛬 Just Landed |
| Week 1–4 | "TFN before first payday", "concession transport card" | 🧾 TFN & Tax · 🚋 Getting Around |
| Month 1–3 | "Find an affordable room", "how does bond work", "is this rental a scam" | 🏠 Housing · 🛡️ Safety |
| Ongoing | "48-hour work limit", "am I being underpaid", "what does OSHC cover" | 🛂 Visas · 💼 Jobs & Pay · 🏥 Health |
| Final year | "485 visa deadline", "claim my super back (DASP)" | 🛂 Visas · 🧾 TFN & Tax |

The modules mirror this stack one-to-one, so the product meets people where they are instead of making them translate their life into government-agency categories.

## 2. The best *form* of output

For this audience, the highest-value answer format is:

1. **A direct, short answer first** (the number, the deadline, the yes/no) — bolded.
2. **Steps as bullets** — newcomers screenshot answers; bullets survive screenshots.
3. **A live link to the official page** — verified server-side, so it can be trusted and re-checked as rules change.
4. **A safety net line** when stakes are high — "for a decision on this, see a MARA agent."

What we deliberately do **not** output:

- **No invented specifics** — no made-up rental listings, prices, processing times. For anything live (listings, current wait times), Kip links to the live source. This is the single biggest trust decision in the product: *when data is dynamic, point, don't quote.*
- **No advice** — "you should apply for the 485" is a migration agent's sentence, not Kip's. Kip says what the 485 is, who it's for, the deadline, and where to apply.
- **No complexity theatre** — no affordability calculators or "visa eligibility scores" in the MVP. A wrong calculator is worse than a right link.

## 3. Why "verify, don't trust" is the product

Every AI chat product claims accuracy. Howdy's differentiator is that verification is *architectural*, not aspirational:

- The model can only cite what's in a curated knowledge base where **every section carries the official source URL**.
- After generation, **deterministic server code checks every link** against an allowlist (.gov.au, .edu.au, and a short list of official platforms). Unverified links are stripped and the UI shows exactly which sources survived.
- The UI displays a **"✅ Verified sources"** panel per answer — the user can always click through to the government page and see for themselves.

For a user whose visa depends on a number ("48 hours per fortnight"), this is the difference between a toy and a tool.

## 4. Why "companion" is the right emotional register

The competition is (a) 200-page government websites, (b) Facebook groups full of confident misinformation, and (c) paid agents. Students trust the Facebook groups because they feel *human*. Kip's voice — warm, Australian, encouraging — competes on that axis while the source verification competes with the government sites on accuracy. The register also does compliance work: a companion *shares what the rules say*; only professionals *advise*. That line is drawn in the system prompt, the UI disclaimer, and the referral pattern (MARA / student legal service / moneysmart).

## 5. Safety as a feature, not a footnote

The population is heavily targeted by scams (fake Home Affairs calls, rental deposit fraud, money muling "jobs"). Howdy treats this as a first-class module (🛡️) and as behaviour: Kip names scams plainly, always includes 000 / Lifeline for distress, and never asks for the very identifiers scammers phish for. The PII guard means even a user who *tries* to paste their TFN gets a gentle refusal and an education moment instead.

## 6. Secure-SaaS posture (summary — full detail in SECURITY.md)

- Nothing stored: no accounts, no message logs, no database → minimal breach surface.
- PII blocked at the door; injection patterns deflected; every model output post-verified.
- Cost-bounded: rate limits, message caps, token caps.

## 7. Roadmap (in trust-preserving order)

1. **Now (MVP):** 10 modules, verified Q&A, listing links, waitlist.
2. **Next:** per-city packs (deeper Brisbane/Sydney/Melbourne content), a "first 30 days" interactive checklist (still static content — no PII), Redis-backed rate limiting.
3. **Later, carefully:** optional accounts with saved checklists (requires a real privacy policy + data-deletion flow), push alerts when a rule in the knowledge base changes ("minimum wage went up on 1 July"), university partnerships.
4. **Only with professional review:** anything that edges toward personalised advice — never before there's a registered human in the loop.
