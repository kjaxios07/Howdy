/**
 * Howdy Jobs — shared reference data, request helpers and the match score.
 */
const STATES = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT'];

/**
 * Categories tuned to where Australian students actually pick up shifts.
 * Order matters — the most common ones sit at the top of every dropdown.
 */
const CATEGORIES = [
  'Hospitality',
  'Retail',
  'Warehouse & Logistics',
  'Delivery & Driving',
  'Cleaning',
  'Customer Service',
  'Administration',
  'Events & Promotions',
  'Tutoring & Education',
  'Childcare',
  'Aged Care & Disability',
  'Healthcare',
  'Construction & Trades',
  'Farm & Agriculture',
  'Security',
  'IT & Tech Support',
  'Other'
];

const EMPLOYMENT_TYPES = ['Casual', 'Part-time', 'Temporary', 'Internship', 'Weekend', 'Evening'];

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// Indicative national minimum for a casual adult (base + 25% loading).
// Listings below this are rejected — always check the current Fair Work rate.
const MIN_HOURLY = Number(process.env.MIN_HOURLY_RATE || 24.95);

// Student visa (subclass 500) work limit during study.
const STUDENT_VISA_FORTNIGHT_HOURS = 48;

/* ── http helpers ───────────────────────────────────────────────────────── */
function json(res, status, body) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.status(status).json(body);
}

const fail = (res, status, error) => json(res, status, { error });

/** Reads a JSON body whether we're behind Express or a bare Node request. */
async function readBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 32768) throw new Error('Request body too large.');
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new Error('Invalid JSON body.');
  }
}

/**
 * Cross-origin form posts cannot set a custom header without passing a CORS
 * preflight, so requiring one on writes gives us CSRF protection without a
 * token round-trip (the session cookie is SameSite=Lax as well).
 */
function csrfOk(req) {
  return req.headers['x-howdy-client'] === 'web';
}

// Control characters, newline excluded so cleanText can keep line breaks.
const CONTROL_CHARS = /[\u0000-\u0009\u000B-\u001F\u007F]/g;

/** Trims, strips control characters (newlines included) and caps length. */
const clean = (value, max) =>
  String(value === undefined || value === null ? '' : value)
    .replace(/[\u0000-\u001F\u007F]/g, ' ')
    .trim()
    .slice(0, max);

/**
 * Same as clean(), but keeps line breaks — job descriptions, responsibilities
 * and cover messages are written as lists and lose their meaning on one line.
 */
const cleanText = (value, max) =>
  String(value === undefined || value === null ? '' : value)
    .replace(/\r\n?/g, '\n')
    .replace(CONTROL_CHARS, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .split('\n')
    .map(line => line.trim())
    .join('\n')
    .trim()
    .slice(0, max);

const isEmail = value => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value);

const isDate = value => /^\d{4}-\d{2}-\d{2}$/.test(String(value || ''));

/** "$30–35/hr", or "$32/hr" when there is no range. */
function payLabel(job) {
  const min = Number(job.payMin);
  const max = Number(job.payMax);
  if (!Number.isFinite(min)) return '';
  const fmt = n => (Number.isInteger(n) ? `${n}` : n.toFixed(2));
  return max && max > min ? `$${fmt(min)}–${fmt(max)}/hr` : `$${fmt(min)}/hr`;
}

/** "10–20 hrs/week", or "15 hrs/week" when there is no range. */
function hoursLabel(job) {
  const min = Number(job.hoursMin);
  const max = Number(job.hoursMax);
  if (!Number.isFinite(min) || min <= 0) return '';
  return max && max > min ? `${min}–${max} hrs/week` : `${min} hrs/week`;
}

/* ── matching ───────────────────────────────────────────────────────────── */
/**
 * MVP match score (0-100) between a student profile and a job. Deterministic
 * and explainable on purpose — every point is attributable to one reason.
 */
function matchScore(profile, job) {
  if (!profile) return null;
  const reasons = [];
  let score = 20; // baseline: the job is open to any eligible student

  if (profile.state && job.state) {
    if (profile.state === job.state) { score += 30; reasons.push(`In your state (${job.state})`); }
    else score -= 10;
  }
  if (profile.suburb && job.suburb
      && profile.suburb.toLowerCase() === job.suburb.toLowerCase()) {
    score += 10;
    reasons.push(`Local to ${job.suburb}`);
  }
  const wanted = Array.isArray(profile.categories) ? profile.categories : [];
  if (wanted.includes(job.category)) { score += 25; reasons.push(`${job.category} is on your list`); }

  const wantHours = Number(profile.hoursPerWeek || 0);
  const jobHours = jobHoursMid(job);
  if (wantHours > 0 && jobHours > 0) {
    const gap = Math.abs(wantHours - jobHours);
    if (gap <= 3) { score += 15; reasons.push('Hours match your availability'); }
    else if (gap <= 7) { score += 8; reasons.push('Hours are close to your availability'); }
  }
  if (jobHours > 0 && jobHours * 2 <= STUDENT_VISA_FORTNIGHT_HOURS) {
    score += 5;
    reasons.push(`Fits the ${STUDENT_VISA_FORTNIGHT_HOURS}h/fortnight study-period limit`);
  }
  const ageDays = (Date.now() - new Date(job.createdAt).getTime()) / 86400000;
  if (ageDays <= 3) { score += 5; reasons.push('Posted this week'); }

  return { score: Math.max(0, Math.min(100, Math.round(score))), reasons: reasons.slice(0, 3) };
}

/** Midpoint of a job's weekly hours range. */
function jobHoursMid(job) {
  const min = Number(job.hoursMin) || 0;
  const max = Number(job.hoursMax) || min;
  return min ? Math.round((min + max) / 2) : 0;
}

/* ── rate limiting ──────────────────────────────────────────────────────── */
// In-memory buckets — fine for one MVP instance, swap for Redis when scaling.
const buckets = new Map();

function rateLimit(key, max, windowMs) {
  const now = Date.now();
  const hits = (buckets.get(key) || []).filter(t => t > now - windowMs);
  if (hits.length >= max) return false;
  hits.push(now);
  buckets.set(key, hits);
  if (buckets.size > 5000) {
    for (const [k, v] of buckets) if (v.every(t => t < now - windowMs)) buckets.delete(k);
  }
  return true;
}

function clientIp(req) {
  const fwd = req.headers['x-forwarded-for'];
  if (typeof fwd === 'string' && fwd) return fwd.split(',')[0].trim();
  return (req.socket && req.socket.remoteAddress) || 'unknown';
}

module.exports = {
  STATES, CATEGORIES, EMPLOYMENT_TYPES, DAYS, MIN_HOURLY, STUDENT_VISA_FORTNIGHT_HOURS,
  json, fail, readBody, csrfOk, clean, cleanText, isEmail, isDate,
  payLabel, hoursLabel, jobHoursMid, matchScore, rateLimit, clientIp
};
