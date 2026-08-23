/**
 * Howdy Jobs — password hashing, signed session cookies and Google sign-in.
 *
 * Sessions are stateless: a base64url payload plus an HMAC signature, stored
 * in an HttpOnly cookie. Set SESSION_SECRET in production, otherwise a random
 * key is generated at boot and every restart signs everyone out.
 */
const crypto = require('crypto');
const store = require('./store');

const COOKIE = 'howdy_jobs_session';
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;

const SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');
if (!process.env.SESSION_SECRET) {
  console.warn('[auth] SESSION_SECRET not set — sessions reset on every restart');
}

const b64 = buf => Buffer.from(buf).toString('base64url');
const sign = value => crypto.createHmac('sha256', SECRET).update(value).digest('base64url');

/* ── passwords ──────────────────────────────────────────────────────────── */
function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString('hex');
  const key = crypto.scryptSync(password, salt, 64).toString('hex');
  return `scrypt$${salt}$${key}`;
}

function verifyPassword(password, stored) {
  if (!stored || !stored.startsWith('scrypt$')) return false;
  const [, salt, key] = stored.split('$');
  const candidate = crypto.scryptSync(password, salt, 64);
  const expected = Buffer.from(key, 'hex');
  return candidate.length === expected.length && crypto.timingSafeEqual(candidate, expected);
}

/* ── sessions ───────────────────────────────────────────────────────────── */
function createToken(userId) {
  const payload = b64(JSON.stringify({ uid: userId, exp: Date.now() + MAX_AGE_MS }));
  return `${payload}.${sign(payload)}`;
}

function readToken(token) {
  if (typeof token !== 'string' || !token.includes('.')) return null;
  const [payload, signature] = token.split('.');
  const expected = sign(payload);
  if (signature.length !== expected.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) return null;
  try {
    const claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    if (!claims.uid || !claims.exp || claims.exp < Date.now()) return null;
    return claims;
  } catch {
    return null;
  }
}

function parseCookies(req) {
  const out = {};
  for (const part of (req.headers.cookie || '').split(';')) {
    const idx = part.indexOf('=');
    if (idx > 0) out[part.slice(0, idx).trim()] = decodeURIComponent(part.slice(idx + 1).trim());
  }
  return out;
}

function setSession(res, userId) {
  const attrs = [
    `${COOKIE}=${createToken(userId)}`,
    'Path=/',
    'HttpOnly',
    'SameSite=Lax',
    `Max-Age=${Math.floor(MAX_AGE_MS / 1000)}`
  ];
  if (process.env.NODE_ENV === 'production') attrs.push('Secure');
  res.setHeader('Set-Cookie', attrs.join('; '));
}

function clearSession(res) {
  res.setHeader('Set-Cookie', `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`);
}

/** Returns the signed-in user record, or null. */
function currentUser(req) {
  const claims = readToken(parseCookies(req)[COOKIE]);
  if (!claims) return null;
  return store.users().find(u => u.id === claims.uid) || null;
}

/* ── Google sign-in ─────────────────────────────────────────────────────── */
/**
 * Verifies a Google Identity Services ID token against Google's tokeninfo
 * endpoint. Enabled only when GOOGLE_CLIENT_ID is configured.
 */
async function verifyGoogleToken(idToken) {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  if (!clientId) throw new Error('Google sign-in is not configured on this deployment.');
  if (typeof idToken !== 'string' || idToken.length < 20) throw new Error('Invalid Google token.');

  const res = await fetch(`https://oauth2.googleapis.com/tokeninfo?id_token=${encodeURIComponent(idToken)}`);
  if (!res.ok) throw new Error('Google could not verify that sign-in.');
  const info = await res.json();

  if (info.aud !== clientId) throw new Error('Google token was issued for a different app.');
  if (info.email_verified !== 'true' && info.email_verified !== true) {
    throw new Error('Your Google email is not verified.');
  }
  if (Number(info.exp) * 1000 < Date.now()) throw new Error('Google sign-in expired — please try again.');

  return { email: String(info.email).toLowerCase(), name: info.name || String(info.email).split('@')[0] };
}

module.exports = {
  COOKIE,
  hashPassword,
  verifyPassword,
  createToken,
  readToken,
  parseCookies,
  setSession,
  clearSession,
  currentUser,
  verifyGoogleToken
};
