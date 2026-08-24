/**
 * Howdy Jobs — accounts and sessions.
 *
 *   POST /api/auth?action=signup   { role, name, email, password }
 *   POST /api/auth?action=login    { email, password }
 *   POST /api/auth?action=google   { credential, role }
 *   POST /api/auth?action=logout
 *   POST /api/auth?action=profile  { ...profile fields }
 *   GET  /api/auth?action=me
 */
const store = require('../lib/store');
const auth = require('../lib/auth');
const {
  STATES, CATEGORIES, json, fail, readBody, csrfOk, clean, cleanText, isEmail, rateLimit, clientIp
} = require('../lib/jobs-core');

/**
 * A student may point their profile at a file they own, or clear it. Anything
 * else keeps whatever is already there.
 */
function cvMeta(body, user) {
  if (!('cv' in body)) return user.profile.cv || null;
  if (!body.cv) return null;
  const owned = store.files().find(f => f.id === body.cv.id && f.ownerId === user.id);
  return owned
    ? { id: owned.id, name: owned.name, type: owned.type, kind: owned.kind, size: owned.size }
    : (user.profile.cv || null);
}

const publicUser = u => u && ({
  id: u.id,
  role: u.role,
  name: u.name,
  email: u.email,
  provider: u.provider,
  profile: u.profile || {},
  employer: u.employer || {}
});

function findByEmail(email) {
  return store.users().find(u => u.email === email);
}

function createUser({ role, name, email, passwordHash, provider }) {
  const user = {
    id: store.id('usr'),
    role,
    name,
    email,
    provider,
    passwordHash,
    createdAt: new Date().toISOString(),
    profile: role === 'student'
      ? { state: '', suburb: '', categories: [], hoursPerWeek: 0, phone: '', bio: '', studyAt: '', cv: null }
      : {},
    employer: role === 'employer'
      ? { business: name, abn: '', website: '', contactPhone: '', state: '', suburb: '' }
      : {}
  };
  store.users().push(user);
  store.save();
  return user;
}

module.exports = async (req, res) => {
  const action = (req.query && req.query.action) || new URL(req.url, 'http://x').searchParams.get('action');

  if (req.method === 'GET') {
    if (action !== 'me') return fail(res, 404, 'Unknown action.');
    return json(res, 200, { user: publicUser(auth.currentUser(req)) });
  }

  if (req.method !== 'POST') return fail(res, 405, 'Method not allowed.');
  if (!csrfOk(req)) return fail(res, 403, 'Missing client header.');

  let body;
  try {
    body = await readBody(req);
  } catch (err) {
    return fail(res, 400, err.message);
  }

  if (action === 'logout') {
    auth.clearSession(res);
    return json(res, 200, { ok: true });
  }

  /* ── sign up ──────────────────────────────────────────────────────────── */
  if (action === 'signup') {
    if (!rateLimit(`signup:${clientIp(req)}`, 5, 60_000)) {
      return fail(res, 429, 'Too many attempts — try again in a minute.');
    }
    const role = body.role === 'employer' ? 'employer' : 'student';
    const name = clean(body.name, 80);
    const email = clean(body.email, 254).toLowerCase();
    const password = String(body.password || '');

    if (name.length < 2) return fail(res, 400, 'Please enter your name.');
    if (!isEmail(email)) return fail(res, 400, 'Please enter a valid email address.');
    if (password.length < 8) return fail(res, 400, 'Password must be at least 8 characters.');
    if (findByEmail(email)) return fail(res, 409, 'An account with that email already exists.');

    const user = createUser({ role, name, email, passwordHash: auth.hashPassword(password), provider: 'password' });
    auth.setSession(res, user.id);
    return json(res, 201, { user: publicUser(user) });
  }

  /* ── sign in ──────────────────────────────────────────────────────────── */
  if (action === 'login') {
    if (!rateLimit(`login:${clientIp(req)}`, 10, 60_000)) {
      return fail(res, 429, 'Too many attempts — try again in a minute.');
    }
    const email = clean(body.email, 254).toLowerCase();
    const user = findByEmail(email);
    if (!user || !auth.verifyPassword(String(body.password || ''), user.passwordHash)) {
      return fail(res, 401, 'Email or password is incorrect.');
    }
    auth.setSession(res, user.id);
    return json(res, 200, { user: publicUser(user) });
  }

  /* ── google sign-in ───────────────────────────────────────────────────── */
  if (action === 'google') {
    if (!rateLimit(`google:${clientIp(req)}`, 10, 60_000)) {
      return fail(res, 429, 'Too many attempts — try again in a minute.');
    }
    let profile;
    try {
      profile = await auth.verifyGoogleToken(body.credential);
    } catch (err) {
      return fail(res, 401, err.message);
    }
    let user = findByEmail(profile.email);
    if (!user) {
      const role = body.role === 'employer' ? 'employer' : 'student';
      user = createUser({ role, name: profile.name, email: profile.email, passwordHash: null, provider: 'google' });
    }
    auth.setSession(res, user.id);
    return json(res, 200, { user: publicUser(user) });
  }

  /* ── profile ──────────────────────────────────────────────────────────── */
  if (action === 'profile') {
    const user = auth.currentUser(req);
    if (!user) return fail(res, 401, 'Please sign in.');

    if (body.name) user.name = clean(body.name, 80);

    if (user.role === 'student') {
      const state = clean(body.state, 3).toUpperCase();
      const categories = Array.isArray(body.categories)
        ? body.categories.filter(c => CATEGORIES.includes(c)).slice(0, 5)
        : user.profile.categories || [];
      user.profile = {
        ...user.profile,
        state: STATES.includes(state) ? state : '',
        suburb: clean(body.suburb, 60),
        categories,
        hoursPerWeek: Math.max(0, Math.min(40, Number(body.hoursPerWeek) || 0)),
        phone: clean(body.phone, 20),
        studyAt: clean(body.studyAt, 100),
        bio: cleanText(body.bio, 600),
        cv: cvMeta(body, user)
      };
    } else {
      const state = clean(body.state, 3).toUpperCase();
      user.employer = {
        ...user.employer,
        business: clean(body.business || user.employer.business || user.name, 100),
        abn: clean(body.abn, 20),
        website: clean(body.website, 200),
        contactPhone: clean(body.contactPhone, 20),
        state: STATES.includes(state) ? state : '',
        suburb: clean(body.suburb, 60)
      };
    }
    store.save();
    return json(res, 200, { user: publicUser(user) });
  }

  return fail(res, 404, 'Unknown action.');
};
