/**
 * Kip Jobs — applications.
 *
 *   POST  /api/applications                  { jobId, message, availability } (students)
 *   GET   /api/applications                  the signed-in student's applications
 *   GET   /api/applications?jobId=job_xxx    applicants for one of your jobs (employers)
 *   PATCH /api/applications?id=app_xxx       { status } (employer who owns the job)
 */
const store = require('../lib/store');
const auth = require('../lib/auth');
const { publicMeta } = require('./files');
const {
  json, fail, readBody, csrfOk, clean, cleanText, rateLimit, clientIp
} = require('../lib/jobs-core');

const STATUSES = ['submitted', 'shortlisted', 'hired', 'declined'];

const query = req => (req.query && Object.keys(req.query).length)
  ? req.query
  : Object.fromEntries(new URL(req.url, 'http://x').searchParams);

module.exports = async (req, res) => {
  const q = query(req);
  const user = auth.currentUser(req);
  if (!user) return fail(res, 401, 'Please sign in.');

  const jobs = store.jobs();
  const applications = store.applications();

  /* ── read ─────────────────────────────────────────────────────────────── */
  if (req.method === 'GET') {
    if (user.role === 'student') {
      const mine = applications
        .filter(a => a.studentId === user.id)
        .map(a => ({ ...a, job: jobs.find(j => j.id === a.jobId) || null }))
        .sort((x, y) => new Date(y.createdAt) - new Date(x.createdAt));
      return json(res, 200, { applications: mine });
    }

    const myJobIds = new Set(jobs.filter(j => j.employerId === user.id).map(j => j.id));
    if (q.jobId && !myJobIds.has(q.jobId)) return fail(res, 403, 'That job belongs to another account.');

    const students = store.users();
    const list = applications
      .filter(a => (q.jobId ? a.jobId === q.jobId : myJobIds.has(a.jobId)))
      .map(a => {
        const student = students.find(u => u.id === a.studentId);
        const job = jobs.find(j => j.id === a.jobId);
        return {
          ...a,
          jobTitle: job ? job.title : 'Removed listing',
          student: student ? {
            name: student.name,
            email: student.email,
            state: student.profile?.state || '',
            suburb: student.profile?.suburb || '',
            hoursPerWeek: student.profile?.hoursPerWeek || 0,
            studyAt: student.profile?.studyAt || '',
            phone: student.profile?.phone || '',
            bio: student.profile?.bio || ''
          } : null
        };
      })
      .sort((x, y) => new Date(y.createdAt) - new Date(x.createdAt));

    return json(res, 200, { applications: list });
  }

  /* ── write ────────────────────────────────────────────────────────────── */
  if (!csrfOk(req)) return fail(res, 403, 'Missing client header.');

  let body;
  try {
    body = await readBody(req);
  } catch (err) {
    return fail(res, 400, err.message);
  }

  if (req.method === 'POST') {
    if (user.role !== 'student') return fail(res, 403, 'Only student accounts can apply.');
    if (!rateLimit(`apply:${clientIp(req)}`, 30, 3600_000)) {
      return fail(res, 429, 'You have applied to a lot of jobs — try again later.');
    }

    const job = jobs.find(j => j.id === body.jobId);
    if (!job) return fail(res, 404, 'That job is no longer listed.');
    if (job.status !== 'open') return fail(res, 400, 'Applications for this job are closed.');
    if (applications.some(a => a.jobId === job.id && a.studentId === user.id)) {
      return fail(res, 409, 'You have already applied to this job.');
    }

    // Only files this student owns can ride along on their application.
    const ownFiles = store.files().filter(f => f.ownerId === user.id);
    const own = id => ownFiles.find(f => f.id === id);

    const cvMeta = own((user.profile && user.profile.cv && user.profile.cv.id) || body.cvId);
    if (!cvMeta) return fail(res, 400, 'Add your CV to your profile before applying.');

    const attachments = (Array.isArray(body.attachmentIds) ? body.attachmentIds : [])
      .slice(0, 3)
      .map(own)
      .filter(Boolean)
      .map(publicMeta);

    const application = {
      id: store.id('app'),
      jobId: job.id,
      studentId: user.id,
      cv: publicMeta(cvMeta),
      attachments,
      message: cleanText(body.message, 1200),
      availability: clean(body.availability, 200),
      status: 'submitted',
      createdAt: new Date().toISOString()
    };
    applications.push(application);
    store.save();
    return json(res, 201, { application });
  }

  if (req.method === 'PATCH') {
    if (user.role !== 'employer') return fail(res, 403, 'Only employers can update applications.');
    const application = applications.find(a => a.id === q.id);
    if (!application) return fail(res, 404, 'Application not found.');
    const job = jobs.find(j => j.id === application.jobId);
    if (!job || job.employerId !== user.id) return fail(res, 403, 'That application belongs to another account.');
    if (!STATUSES.includes(body.status)) return fail(res, 400, 'Unknown status.');

    application.status = body.status;
    store.save();
    return json(res, 200, { application });
  }

  return fail(res, 405, 'Method not allowed.');
};
