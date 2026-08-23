/**
 * Howdy Jobs — saved jobs (the ♡ on a listing).
 *
 *   POST /api/saved  { jobId }  toggles the save, returns { saved: true|false }
 *
 * The list itself comes back from GET /api/jobs?saved=true.
 */
const store = require('../lib/store');
const auth = require('../lib/auth');
const { json, fail, readBody, csrfOk } = require('../lib/jobs-core');

module.exports = async (req, res) => {
  if (req.method !== 'POST') return fail(res, 405, 'Method not allowed.');
  if (!csrfOk(req)) return fail(res, 403, 'Missing client header.');

  const user = auth.currentUser(req);
  if (!user) return fail(res, 401, 'Please sign in.');
  if (user.role !== 'student') return fail(res, 403, 'Only student accounts can save jobs.');

  let body;
  try {
    body = await readBody(req);
  } catch (err) {
    return fail(res, 400, err.message);
  }

  const job = store.jobs().find(j => j.id === body.jobId);
  if (!job) return fail(res, 404, 'That job is no longer listed.');

  const saved = store.savedJobs();
  const existing = saved.findIndex(s => s.jobId === job.id && s.studentId === user.id);

  if (existing > -1) {
    saved.splice(existing, 1);
    store.save();
    return json(res, 200, { saved: false });
  }

  saved.push({
    id: store.id('sav'),
    jobId: job.id,
    studentId: user.id,
    createdAt: new Date().toISOString()
  });
  store.save();
  return json(res, 201, { saved: true });
};
