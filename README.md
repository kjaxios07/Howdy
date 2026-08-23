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
| `/jobs` | Front door — two options: student or business |
| `/jobs/browse` | Student job board — search, match scores, apply, track applications |
| `/employer` | Employer dashboard — post jobs, manage listings, review applicants, promote on Instagram |

## Howdy Jobs

**Students** sign in with Google or an email and password, save a profile (state, suburb, hours a week,
job categories, where they study), then search, save (♡) and apply. Each listing is scored against the
profile and the board is sorted best-match-first, with the reasons shown on the listing.

**Employers and vendors** create an account, publish a casual or part-time role, and shortlist, hire or
decline applicants from one dashboard. Listings below the indicative minimum hourly rate are rejected
before they go live.

### Job fields

| Field | Notes |
| --- | --- |
| Title | 4–100 characters |
| Category | One of the 17 AU categories below |
| Employment type | Casual, Part-time, Temporary, Internship, Weekend, Evening |
| Suburb + state | Free-text suburb, state from the eight AU states and territories |
| Pay | `payMin`–`payMax` per hour; `payMin` must clear the Fair Work floor |
| Hours | `hoursMin`–`hoursMax` per week, 1–40 |
| About the job | 30–3000 characters |
| Responsibilities | One per line, rendered as bullets |
| Requirements | One per line, rendered as bullets |
| Days needed | Any of Mon–Sun |
| Start date | Optional |
| Applications close | Optional |

### Categories

Hospitality · Retail · Warehouse & Logistics · Delivery & Driving · Cleaning · Customer Service ·
Administration · Events & Promotions · Tutoring & Education · Childcare · Aged Care & Disability ·
Healthcare · Construction & Trades · Farm & Agriculture · Security · IT & Tech Support · Other

### Promote on Instagram

Publishing a job opens the share pack automatically — that is the whole automation. For any listing
(button: **Promote**) it produces:

- a **1080×1080 feed post** and a **1080×1920 story / Reel cover**, drawn on a canvas in the browser from
  the job's own fields — download as PNG, or hit **Share** on a phone to hand the image and caption
  straight to Instagram through the OS share sheet;
- a **caption** with the pay, location and shift pattern, plus Australian hashtags picked from the state
  and category (`#brisbanejobs #studentjobs #casualjobs #hospitalityjobs …`), editable before posting;
- a **15-second Reel script** — four scenes with the shot, the on-screen text and the line to say, plus
  audio and posting-time tips.

Nothing is posted on the business's behalf: publishing straight to Instagram needs an Instagram Business
account connected to a Meta app with a Graph API token, which is a per-business setup, not an MVP feature.
The generator is deliberately independent of that — a business can post the image by hand today.

### API

All endpoints return JSON. Writes require the `X-Howdy-Client: web` header (a lightweight CSRF guard that
works alongside the `SameSite=Lax` session cookie).

| Endpoint | Purpose |
| --- | --- |
| `GET /api/jobs-config` | States, categories, job types, minimum rate, Google client id |
| `POST /api/auth?action=signup\|login\|google\|logout\|profile` | Accounts and sessions |
| `GET /api/auth?action=me` | Current user |
| `GET /api/jobs` | Public board — filters: `state`, `category`, `employmentType`, `q`, `minPay`, `postedWithin`, `sort`; `mine=true` (employer's own) or `saved=true` (student's saved) |
| `GET /api/jobs?id=…` | One listing |
| `POST /api/jobs` | Publish a listing (employers) |
| `PATCH /api/jobs?id=…` | Open or close a listing (owner only) |
| `DELETE /api/jobs?id=…` | Remove a listing and its applications (owner only) |
| `POST /api/saved` | Toggle ♡ on a job (students) |
| `GET /api/social?id=…` | Instagram caption, hashtags, alt text and Reel script for a listing |
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

### PWA

`manifest.webmanifest` plus `sw.js` make the site installable: Android/Chrome shows an install prompt
(surfaced on the **Install Howdy Jobs** button on `/jobs`), iOS installs through Share → Add to Home
Screen, and the service worker caches the app shell so the pages open offline. `/api/*` is never cached,
so job data is always live. Package it with Capacitor later if you need App Store presence.

### Data

The MVP stores users, jobs, applications and saved jobs in one JSON file, seeded with 17 listings across
NSW, VIC, QLD, SA, WA, ACT, TAS and NT so the board is never empty. Seeded employers have no password, so no one can sign in
as them. Passwords are hashed with scrypt; sessions are HMAC-signed HttpOnly cookies. **Move to a real database
(Postgres/Supabase) before production** — serverless filesystems are ephemeral, and the JSON store has no
concurrency control.

### Compliance notes

Pay rates are set by employers and checked against an indicative floor only — the current award rate lives at
fairwork.gov.au. Student visa (subclass 500) holders can generally work up to 48 hours a fortnight while their
course is in session; both surfaces say so. Howdy Jobs is a listing platform, not the employer.
