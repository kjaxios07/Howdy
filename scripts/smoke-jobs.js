/**
 * Howdy Jobs — end-to-end smoke test.
 *
 * Boots the Express app on a spare port against a throwaway data file and
 * walks the full flow: employer signs up → posts a job → student signs up →
 * sets a profile → applies → employer shortlists.
 *
 *   node scripts/smoke-jobs.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PORT = 4188;
const BASE = `http://127.0.0.1:${PORT}`;
const DATA_FILE = path.join(os.tmpdir(), `howdy-jobs-smoke-${Date.now()}.json`);

let passed = 0;
let failed = 0;

function check(label, condition, detail) {
  if (condition) {
    passed++;
    console.log(`  ok   ${label}`);
  } else {
    failed++;
    console.log(`  FAIL ${label}${detail ? ` — ${JSON.stringify(detail)}` : ''}`);
  }
}

function makeClient() {
  let cookie = '';
  return async function call(pathname, options = {}) {
    const headers = { 'X-Howdy-Client': 'web' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (cookie) headers.Cookie = cookie;
    if (options.noClientHeader) delete headers['X-Howdy-Client'];

    const res = await fetch(BASE + pathname, {
      method: options.method || (options.body !== undefined ? 'POST' : 'GET'),
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined
    });
    const setCookie = res.headers.get('set-cookie');
    if (setCookie) cookie = setCookie.split(';')[0];
    let body = null;
    try { body = await res.json(); } catch {}
    return { status: res.status, body };
  };
}

async function waitForServer(attempts = 60) {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(`${BASE}/api/jobs-config`);
      if (res.ok) return;
    } catch {}
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error('server did not start');
}

(async () => {
  const server = spawn(process.execPath, [path.join(__dirname, '..', 'server.js')], {
    env: { ...process.env, PORT: String(PORT), HOWDY_DATA_FILE: DATA_FILE, SESSION_SECRET: 'smoke-test-secret' },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  server.stderr.on('data', d => process.stderr.write(`[server] ${d}`));

  try {
    await waitForServer();

    /* config + seeded board */
    const anon = makeClient();
    const config = await anon('/api/jobs-config');
    check('config lists 8 states', config.body.states.length === 8, config.body.states);

    const board = await anon('/api/jobs');
    check('seeded jobs are listed', board.body.total >= 10, board.body.total);
    check('anonymous browsing gets no match scores', !board.body.jobs[0].match);

    const filtered = await anon('/api/jobs?state=VIC');
    check('state filter works', filtered.body.jobs.every(j => j.state === 'VIC'), filtered.body.total);

    const searched = await anon('/api/jobs?q=barista');
    check('keyword search works', searched.body.total >= 1 && /barista/i.test(searched.body.jobs[0].title));

    check('anonymous apply is rejected',
      (await anon('/api/applications', { body: { jobId: 'x' } })).status === 401);
    check('cross-origin style post is rejected without client header',
      (await anon('/api/auth?action=login', { body: {}, noClientHeader: true })).status === 403);

    /* employer */
    const employer = makeClient();
    const signup = await employer('/api/auth?action=signup', {
      body: { role: 'employer', name: 'Ravi Coffee Co', email: 'owner@ravicoffee.test', password: 'CoffeeBeans12' }
    });
    check('employer signup succeeds', signup.status === 201 && signup.body.user.role === 'employer', signup.body);
    check('duplicate email is rejected',
      (await employer('/api/auth?action=signup', {
        body: { role: 'employer', name: 'Dupe', email: 'owner@ravicoffee.test', password: 'CoffeeBeans12' }
      })).status === 409);
    check('short password is rejected',
      (await makeClient()('/api/auth?action=signup', {
        body: { role: 'student', name: 'Ann', email: 'ann@student.test', password: 'short' }
      })).status === 400);

    const underpaid = await employer('/api/jobs', {
      body: {
        title: 'Weekend barista', category: 'Hospitality', jobType: 'Casual', hoursPerWeek: 14,
        state: 'NSW', suburb: 'Newtown', payRate: 12,
        description: 'Saturday and Sunday espresso bar shifts with full training provided.'
      }
    });
    check('below-minimum pay is blocked', underpaid.status === 400, underpaid.body);

    const posted = await employer('/api/jobs', {
      body: {
        title: 'Weekend barista', category: 'Hospitality', jobType: 'Casual', hoursPerWeek: 14,
        state: 'NSW', suburb: 'Newtown', payRate: 33.5,
        description: 'Saturday and Sunday espresso bar shifts with full training provided.',
        requirements: 'Reliable timekeeping. Valid Australian work rights.'
      }
    });
    check('employer can post a job', posted.status === 201, posted.body);
    const jobId = posted.body.job && posted.body.job.id;

    const mine = await employer('/api/jobs?mine=true');
    check('employer sees only their own jobs',
      mine.body.jobs.length === 1 && mine.body.jobs[0].id === jobId, mine.body.total);

    /* student */
    const student = makeClient();
    const studentSignup = await student('/api/auth?action=signup', {
      body: { role: 'student', name: 'Mei Tan', email: 'mei@student.test', password: 'StudyHard99' }
    });
    check('student signup succeeds', studentSignup.status === 201, studentSignup.body);

    const profile = await student('/api/auth?action=profile', {
      body: { state: 'NSW', suburb: 'Newtown', categories: ['Hospitality'], hoursPerWeek: 14, studyAt: 'UTS' }
    });
    check('student profile saves', profile.body.user.profile.state === 'NSW', profile.body);

    const studentBoard = await student('/api/jobs');
    const match = studentBoard.body.jobs.find(j => j.id === jobId);
    check('matched job scores highly', match && match.match.score >= 90, match && match.match);
    check('best match sorts first', studentBoard.body.jobs[0].id === jobId, studentBoard.body.jobs[0].title);

    check('students cannot post jobs',
      (await student('/api/jobs', { body: { title: 'Nope' } })).status === 403);

    const applied = await student('/api/applications', {
      body: { jobId, message: 'I live ten minutes away and have two years of cafe experience.', availability: 'Weekends' }
    });
    check('student can apply', applied.status === 201, applied.body);
    check('duplicate application is rejected',
      (await student('/api/applications', { body: { jobId, message: 'again' } })).status === 409);

    const myApps = await student('/api/applications');
    check('student sees their application',
      myApps.body.applications.length === 1 && myApps.body.applications[0].job.id === jobId);

    /* employer reviews */
    const applicants = await employer('/api/applications');
    check('employer sees the applicant',
      applicants.body.applications.length === 1
      && applicants.body.applications[0].student.email === 'mei@student.test', applicants.body);

    const appId = applicants.body.applications[0].id;
    const shortlisted = await employer(`/api/applications?id=${appId}`, {
      method: 'PATCH', body: { status: 'shortlisted' }
    });
    check('employer can shortlist', shortlisted.body.application.status === 'shortlisted', shortlisted.body);

    /* isolation between accounts */
    const other = makeClient();
    await other('/api/auth?action=signup', {
      body: { role: 'employer', name: 'Rival Cafe', email: 'rival@cafe.test', password: 'RivalPass11' }
    });
    check('another employer cannot read your applicants',
      (await other(`/api/applications?jobId=${jobId}`)).status === 403);
    check('another employer cannot close your job',
      (await other(`/api/jobs?id=${jobId}`, { method: 'PATCH', body: { status: 'closed' } })).status === 403);

    /* closing a job hides it */
    await employer(`/api/jobs?id=${jobId}`, { method: 'PATCH', body: { status: 'closed' } });
    const afterClose = await anon('/api/jobs');
    check('closed jobs drop off the public board', !afterClose.body.jobs.some(j => j.id === jobId));

    /* pages render */
    for (const page of ['/jobs', '/jobs/browse', '/employer', '/assets/howdy-jobs.css', '/assets/howdy-jobs.js']) {
      const res = await fetch(BASE + page);
      check(`${page} serves`, res.ok, res.status);
    }

    /* sign out */
    await student('/api/auth?action=logout', { body: {} });
    check('logout clears the session', (await student('/api/auth?action=me')).body.user === null);
  } catch (err) {
    failed++;
    console.error('  FAIL harness error —', err.message);
  } finally {
    server.kill();
    try { fs.unlinkSync(DATA_FILE); } catch {}
  }

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})();
