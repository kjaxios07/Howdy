/**
 * Howdy Jobs — job listings.
 *
 *   GET    /api/jobs              list + filters
 *                                 (state, category, employmentType, q, minPay, postedWithin, sort)
 *   GET    /api/jobs?id=job_xxx   single listing
 *   GET    /api/jobs?mine=true    the signed-in employer's listings
 *   GET    /api/jobs?saved=true   the signed-in student's saved jobs
 *   POST   /api/jobs              create (employers only)
 *   PATCH  /api/jobs?id=job_xxx   { status } — open or close (owner only)
 *   DELETE /api/jobs?id=job_xxx   remove a listing (owner only)
 */
const store = require('../lib/store');
const auth = require('../lib/auth');
const {
  STATES, CATEGORIES, EMPLOYMENT_TYPES, DAYS, MIN_HOURLY,
  json, fail, readBody, csrfOk, clean, cleanText, isDate, matchScore, rateLimit, clientIp
} = require('../lib/jobs-core');

const query = req => (req.query && Object.keys(req.query).length)
  ? req.query
  : Object.fromEntries(new URL(req.url, 'http://x').searchParams);

function decorate(job, user, applications, saved) {
  const out = {
    ...job,
    applicantCount: applications.filter(a => a.jobId === job.id).length
  };
  if (user && user.role === 'student') {
    out.match = matchScore(user.profile, job);
    out.applied = applications.some(a => a.jobId === job.id && a.studentId === user.id);
    out.saved = saved.some(s => s.jobId === job.id && s.studentId === user.id);
  }
  return out;
}

module.exports = async (req, res) => {
  const q = query(req);
  const user = auth.currentUser(req);
  const jobs = store.jobs();
  const applications = store.applications();
  const saved = store.savedJobs();

  /* ── read ─────────────────────────────────────────────────────────────── */
  if (req.method === 'GET') {
    if (q.id) {
      const job = jobs.find(j => j.id === q.id);
      if (!job) return fail(res, 404, 'That job is no longer listed.');
      const employer = store.users().find(u => u.id === job.employerId);
      return json(res, 200, {
        job: decorate(job, user, applications, saved),
        employer: employer ? {
          business: employer.employer.business,
          industry: employer.employer.industry || '',
          suburb: employer.employer.suburb || '',
          state: employer.employer.state || '',
          website: employer.employer.website || '',
          verified: !!employer.employer.verified
        } : null
      });
    }

    let list = jobs.slice();

    if (q.mine === 'true') {
      if (!user || user.role !== 'employer') return fail(res, 401, 'Employer sign-in required.');
      list = list.filter(j => j.employerId === user.id);
    } else if (q.saved === 'true') {
      if (!user || user.role !== 'student') return fail(res, 401, 'Student sign-in required.');
      const mine = new Set(saved.filter(s => s.studentId === user.id).map(s => s.jobId));
      list = list.filter(j => mine.has(j.id));
    } else {
      list = list.filter(j => j.status === 'open');
    }

    const state = String(q.state || '').toUpperCase();
    if (STATES.includes(state)) list = list.filter(j => j.state === state);
    if (q.category && CATEGORIES.includes(q.category)) list = list.filter(j => j.category === q.category);
    if (q.employmentType && EMPLOYMENT_TYPES.includes(q.employmentType)) {
      list = list.filter(j => j.employmentType === q.employmentType);
    }

    const minPay = Number(q.minPay);
    if (Number.isFinite(minPay) && minPay > 0) {
      list = list.filter(j => Number(j.payMax || j.payMin) >= minPay);
    }

    const withinDays = Number(q.postedWithin);
    if (Number.isFinite(withinDays) && withinDays > 0) {
      const cutoff = Date.now() - withinDays * 86400000;
      list = list.filter(j => new Date(j.createdAt).getTime() >= cutoff);
    }

    const term = String(q.q || '').trim().toLowerCase();
    if (term) {
      list = list.filter(j => [j.title, j.business, j.suburb, j.category, j.description]
        .join(' ').toLowerCase().includes(term));
    }

    const decorated = list.map(j => decorate(j, user, applications, saved));

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

  let body = {};
  if (req.method !== 'DELETE') {
    try {
      body = await readBody(req);
    } catch (err) {
      return fail(res, 400, err.message);
    }
  }

  if (req.method === 'POST') {
    if (!rateLimit(`post-job:${clientIp(req)}`, 20, 3600000)) {
      return fail(res, 429, 'Posting limit reached — try again later.');
    }

    const title = clean(body.title, 100);
    const state = clean(body.state, 3).toUpperCase();
    const suburb = clean(body.suburb, 60);
    const category = clean(body.category, 40);
    const employmentType = clean(body.employmentType, 20);
    const payMin = Number(body.payMin);
    const payMax = body.payMax === '' || body.payMax === undefined || body.payMax === null
      ? payMin
      : Number(body.payMax);
    const hoursMin = Number(body.hoursMin);
    const hoursMax = body.hoursMax === '' || body.hoursMax === undefined || body.hoursMax === null
      ? hoursMin
      : Number(body.hoursMax);
    const description = cleanText(body.description, 3000);

    if (title.length < 4) return fail(res, 400, 'Give the role a clear title.');
    if (!STATES.includes(state)) return fail(res, 400, 'Choose an Australian state or territory.');
    if (!suburb) return fail(res, 400, 'Add the suburb or city.');
    if (!CATEGORIES.includes(category)) return fail(res, 400, 'Choose a job category.');
    if (!EMPLOYMENT_TYPES.includes(employmentType)) return fail(res, 400, 'Choose an employment type.');
    if (!Number.isFinite(payMin) || payMin <= 0) return fail(res, 400, 'Add an hourly pay rate.');
    if (payMin < MIN_HOURLY) {
      return fail(res, 400, `Pay must be at least $${MIN_HOURLY.toFixed(2)}/hour — check the current Fair Work minimum.`);
    }
    if (!Number.isFinite(payMax) || payMax < payMin) return fail(res, 400, 'Maximum pay cannot be below the minimum.');
    if (!Number.isFinite(hoursMin) || hoursMin < 1 || hoursMin > 40) {
      return fail(res, 400, 'Hours per week must be between 1 and 40.');
    }
    if (!Number.isFinite(hoursMax) || hoursMax < hoursMin || hoursMax > 40) {
      return fail(res, 400, 'Maximum hours must be between the minimum and 40.');
    }
    if (description.length < 30) return fail(res, 400, 'Add a short description (at least 30 characters).');
    if (body.startsOn && !isDate(body.startsOn)) return fail(res, 400, 'Start date must be a valid date.');
    if (body.closesOn && !isDate(body.closesOn)) return fail(res, 400, 'Application deadline must be a valid date.');

    const job = {
      id: store.id('job'),
      employerId: user.id,
      business: clean(user.employer.business || user.name, 100),
      verified: !!user.employer.verified,
      title,
      category,
      employmentType,
      state,
      suburb,
      payMin: Math.round(payMin * 100) / 100,
      payMax: Math.round(payMax * 100) / 100,
      hoursMin: Math.round(hoursMin),
      hoursMax: Math.round(hoursMax),
      description,
      responsibilities: cleanText(body.responsibilities, 1500),
      requirements: cleanText(body.requirements, 1500),
      days: Array.isArray(body.days) ? body.days.filter(d => DAYS.includes(d)) : [],
      startsOn: isDate(body.startsOn) ? body.startsOn : '',
      closesOn: isDate(body.closesOn) ? body.closesOn : '',
      status: 'open',
      createdAt: new Date().toISOString()
    };
    store.jobs().push(job);
    store.save();
    return json(res, 201, { job: decorate(job, user, applications, saved) });
  }

  const job = jobs.find(j => j.id === q.id);
  if (!job) return fail(res, 404, 'Job not found.');
  if (job.employerId !== user.id) return fail(res, 403, 'That job belongs to another account.');

  if (req.method === 'PATCH') {
    if (!['open', 'closed'].includes(body.status)) return fail(res, 400, 'Status must be open or closed.');
    job.status = body.status;
    store.save();
    return json(res, 200, { job: decorate(job, user, applications, saved) });
  }

  if (req.method === 'DELETE') {
    jobs.splice(jobs.indexOf(job), 1);
    // Applications and saves for a removed listing go with it.
    for (let i = applications.length - 1; i >= 0; i--) {
      if (applications[i].jobId === job.id) applications.splice(i, 1);
    }
    for (let i = saved.length - 1; i >= 0; i--) {
      if (saved[i].jobId === job.id) saved.splice(i, 1);
    }
    store.save();
    return json(res, 200, { ok: true });
  }

  return fail(res, 405, 'Method not allowed.');
};
