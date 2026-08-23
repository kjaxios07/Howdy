/**
 * Howdy Jobs — job listings.
 *
 *   GET   /api/jobs                 list + filters (state, category, jobType, q, mine)
 *   GET   /api/jobs?id=job_xxx      single listing
 *   POST  /api/jobs                 create (employers only)
 *   PATCH /api/jobs?id=job_xxx      { status: 'open' | 'closed' } (owner only)
 */
const store = require('../lib/store');
const auth = require('../lib/auth');
const {
  STATES, CATEGORIES, JOB_TYPES, MIN_HOURLY,
  json, fail, readBody, csrfOk, clean, matchScore, rateLimit, clientIp
} = require('../lib/jobs-core');

const query = req => (req.query && Object.keys(req.query).length)
  ? req.query
  : Object.fromEntries(new URL(req.url, 'http://x').searchParams);

function decorate(job, user, applications) {
  const applicantCount = applications.filter(a => a.jobId === job.id).length;
  const out = { ...job, applicantCount };
  if (user && user.role === 'student') {
    out.match = matchScore(user.profile, job);
    out.applied = applications.some(a => a.jobId === job.id && a.studentId === user.id);
  }
  return out;
}

module.exports = async (req, res) => {
  const q = query(req);
  const user = auth.currentUser(req);
  const jobs = store.jobs();
  const applications = store.applications();

  /* ── read ─────────────────────────────────────────────────────────────── */
  if (req.method === 'GET') {
    if (q.id) {
      const job = jobs.find(j => j.id === q.id);
      if (!job) return fail(res, 404, 'That job is no longer listed.');
      return json(res, 200, { job: decorate(job, user, applications) });
    }

    let list = jobs.slice();

    if (q.mine === 'true') {
      if (!user || user.role !== 'employer') return fail(res, 401, 'Employer sign-in required.');
      list = list.filter(j => j.employerId === user.id);
    } else {
      list = list.filter(j => j.status === 'open');
    }

    const state = String(q.state || '').toUpperCase();
    if (STATES.includes(state)) list = list.filter(j => j.state === state);
    if (q.category && CATEGORIES.includes(q.category)) list = list.filter(j => j.category === q.category);
    if (q.jobType && JOB_TYPES.includes(q.jobType)) list = list.filter(j => j.jobType === q.jobType);

    const term = String(q.q || '').trim().toLowerCase();
    if (term) {
      list = list.filter(j => [j.title, j.business, j.suburb, j.category, j.description]
        .join(' ').toLowerCase().includes(term));
    }

    let decorated = list.map(j => decorate(j, user, applications));

    // Students sort by match first; everyone else by newest.
    if (user && user.role === 'student' && q.sort !== 'recent') {
      decorated.sort((a, b) => (b.match?.score || 0) - (a.match?.score || 0)
        || new Date(b.createdAt) - new Date(a.createdAt));
    } else {
      decorated.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    }

    return json(res, 200, { jobs: decorated, total: decorated.length });
  }

  /* ── write ────────────────────────────────────────────────────────────── */
  if (!csrfOk(req)) return fail(res, 403, 'Missing client header.');
  if (!user) return fail(res, 401, 'Please sign in.');
  if (user.role !== 'employer') return fail(res, 403, 'Only employer accounts can manage jobs.');

  let body;
  try {
    body = await readBody(req);
  } catch (err) {
    return fail(res, 400, err.message);
  }

  if (req.method === 'POST') {
    if (!rateLimit(`post-job:${clientIp(req)}`, 20, 3600_000)) {
      return fail(res, 429, 'Posting limit reached — try again later.');
    }

    const title = clean(body.title, 100);
    const state = clean(body.state, 3).toUpperCase();
    const suburb = clean(body.suburb, 60);
    const category = clean(body.category, 40);
    const jobType = clean(body.jobType, 20);
    const payRate = Number(body.payRate);
    const hoursPerWeek = Number(body.hoursPerWeek);
    const description = clean(body.description, 3000);

    if (title.length < 4) return fail(res, 400, 'Give the role a clear title.');
    if (!STATES.includes(state)) return fail(res, 400, 'Choose an Australian state or territory.');
    if (!suburb) return fail(res, 400, 'Add the suburb or city.');
    if (!CATEGORIES.includes(category)) return fail(res, 400, 'Choose a job category.');
    if (!JOB_TYPES.includes(jobType)) return fail(res, 400, 'Choose casual or part-time.');
    if (!Number.isFinite(payRate) || payRate <= 0) return fail(res, 400, 'Add an hourly pay rate.');
    if (payRate < MIN_HOURLY) {
      return fail(res, 400, `Pay must be at least $${MIN_HOURLY.toFixed(2)}/hour — check the current Fair Work minimum.`);
    }
    if (!Number.isFinite(hoursPerWeek) || hoursPerWeek < 1 || hoursPerWeek > 40) {
      return fail(res, 400, 'Hours per week must be between 1 and 40.');
    }
    if (description.length < 30) return fail(res, 400, 'Add a short description (at least 30 characters).');

    const job = {
      id: store.id('job'),
      employerId: user.id,
      business: clean(user.employer.business || user.name, 100),
      title,
      category,
      jobType,
      state,
      suburb,
      payRate: Math.round(payRate * 100) / 100,
      payBasis: 'hour',
      hoursPerWeek: Math.round(hoursPerWeek),
      description,
      requirements: clean(body.requirements, 1000),
      closesOn: /^\d{4}-\d{2}-\d{2}$/.test(body.closesOn || '') ? body.closesOn : '',
      status: 'open',
      createdAt: new Date().toISOString()
    };
    store.jobs().push(job);
    store.save();
    return json(res, 201, { job: decorate(job, user, applications) });
  }

  if (req.method === 'PATCH') {
    const job = jobs.find(j => j.id === q.id);
    if (!job) return fail(res, 404, 'Job not found.');
    if (job.employerId !== user.id) return fail(res, 403, 'That job belongs to another account.');
    if (!['open', 'closed'].includes(body.status)) return fail(res, 400, 'Status must be open or closed.');
    job.status = body.status;
    store.save();
    return json(res, 200, { job: decorate(job, user, applications) });
  }

  return fail(res, 405, 'Method not allowed.');
};
