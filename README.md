# Howdy

Australia's AI Life Copilot for international students and new migrants — plus **Howdy Jobs**, a simple
job board for student part-time and casual work across every Australian state.

```bash
npm install
npm start          # http://localhost:3000
npm run test:jobs  # end-to-end smoke test of the jobs platform
```

## Pages

| Route | What it is |
| --- | --- |
| `/` | Howdy marketing site |
| `/chat` | Kip, the AI life copilot |
| `/jobs` | Student job board — search, match scores, apply, track applications |
| `/employer` | Employer dashboard — post jobs, manage listings, review applicants |

## Howdy Jobs

**Students** sign in with Google or an email and password, save a profile (state, suburb, hours a week,
job categories, where they study), then browse and apply. Each listing is scored against the profile and
the board is sorted best-match-first, with the reasons shown on the listing.

**Employers and vendors** create an account, publish a casual or part-time role — title, category, state,
suburb, hourly rate, hours a week, description, requirements, closing date — and then shortlist, hire or
decline applicants from one dashboard. Listings below the indicative minimum hourly rate are rejected
before they go live.

### API

All endpoints return JSON. Writes require the `X-Howdy-Client: web` header (a lightweight CSRF guard that
works alongside the `SameSite=Lax` session cookie).

| Endpoint | Purpose |
| --- | --- |
| `GET /api/jobs-config` | States, categories, job types, minimum rate, Google client id |
| `POST /api/auth?action=signup\|login\|google\|logout\|profile` | Accounts and sessions |
| `GET /api/auth?action=me` | Current user |
| `GET /api/jobs` | Public board — filters: `state`, `category`, `jobType`, `q`, `sort`; `mine=true` for an employer's own listings |
| `GET /api/jobs?id=…` | One listing |
| `POST /api/jobs` | Publish a listing (employers) |
| `PATCH /api/jobs?id=…` | Open or close a listing (owner only) |
| `POST /api/applications` | Apply to a job (students) |
| `GET /api/applications` | A student's applications, or an employer's applicants (`?jobId=…`) |
| `PATCH /api/applications?id=…` | Set status: `submitted`, `shortlisted`, `hired`, `declined` |

### Matching

`lib/jobs-core.js` scores a student profile against a job out of 100 — same state (+30), same suburb (+10),
a wanted category (+25), hours within a few of what they want (+15/+8), fits the 48-hour fortnight study-period
limit (+5), posted this week (+5), from a baseline of 20. Every point maps to a reason the student can read,
so there is nothing opaque to explain away.

### Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `SESSION_SECRET` | random per boot | Set it, or every restart signs everyone out |
| `GOOGLE_CLIENT_ID` | unset | Set to enable "Continue with Google"; the email form works either way |
| `HOWDY_DATA_FILE` | `./data/howdy-jobs.json` | JSON store; falls back to memory on a read-only filesystem |
| `MIN_HOURLY_RATE` | `24.95` | Indicative casual minimum used to block underpaid listings |

### Data

The MVP stores users, jobs and applications in one JSON file, seeded with 13 listings across NSW, VIC, QLD,
SA, WA, ACT, TAS and NT so the board is never empty. Seeded employers have no password, so no one can sign in
as them. Passwords are hashed with scrypt; sessions are HMAC-signed HttpOnly cookies. **Move to a real database
(Postgres/Supabase) before production** — serverless filesystems are ephemeral, and the JSON store has no
concurrency control.

### Compliance notes

Pay rates are set by employers and checked against an indicative floor only — the current award rate lives at
fairwork.gov.au. Student visa (subclass 500) holders can generally work up to 48 hours a fortnight while their
course is in session; both surfaces say so. Howdy Jobs is a listing platform, not the employer.
