/**
 * Howdy Jobs — shared reference data, request helpers and the match score.
 */
const STATES = ['NSW', 'VIC', 'QLD', 'WA', 'SA', 'TAS', 'ACT', 'NT'];

const CATEGORIES = [
  'Hospitality', 'Retail', 'Warehouse', 'Delivery', 'Events',
  'Tutoring', 'Administration', 'Cleaning', 'Childcare', 'Customer Service'
];

const JOB_TYPES = ['Casual', 'Part-time'];

// Indicative national minimum for a casual adult (base + 25% loading).
// Employers see a warning below this — always check the current Fair Work rate.
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

/** Trims, strips control characters and caps length. */
const clean = (value, max) =>
  String(value === undefined || value === null ? '' : value)
    .replace(/[\u0000-\u001F\u007F]/g, ' ')
    .trim()
    .slice(0, max);

const isEmail = value => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value);

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

  const hours = Number(profile.hoursPerWeek || 0);
  if (hours > 0 && job.hoursPerWeek) {
    const gap = Math.abs(hours - job.hoursPerWeek);
    if (gap <= 3) { score += 15; reasons.push('Hours match your availability'); }
    else if (gap <= 7) { score += 8; reasons.push('Hours are close to your availability'); }
  }
  if (job.hoursPerWeek && job.hoursPerWeek * 2 <= STUDENT_VISA_FORTNIGHT_HOURS) {
    score += 5;
    reasons.push(`Fits the ${STUDENT_VISA_FORTNIGHT_HOURS}h/fortnight study-period limit`);
  }
  const ageDays = (Date.now() - new Date(job.createdAt).getTime()) / 86400000;
  if (ageDays <= 3) { score += 5; reasons.push('Posted this week'); }

  return { score: Math.max(0, Math.min(100, Math.round(score))), reasons: reasons.slice(0, 3) };
}

module.exports = {
  STATES, CATEGORIES, JOB_TYPES, MIN_HOURLY, STUDENT_VISA_FORTNIGHT_HOURS,
  json, fail, readBody, csrfOk, clean, isEmail, matchScore
};

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

module.exports.rateLimit = rateLimit;
module.exports.clientIp = clientIp;
