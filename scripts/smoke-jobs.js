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
    check('config lists AU job categories',
      config.body.categories.includes('Hospitality')
      && config.body.categories.includes('Warehouse & Logistics')
      && config.body.categories.includes('Delivery & Driving')
      && config.body.categories.length >= 15, config.body.categories);
    check('config lists all employment types',
      ['Casual', 'Part-time', 'Temporary', 'Internship', 'Weekend', 'Evening']
        .every(t => config.body.employmentTypes.includes(t)), config.body.employmentTypes);

    const board = await anon('/api/jobs');
    check('seeded jobs are listed', board.body.total >= 10, board.body.total);
    check('anonymous browsing gets no match scores', !board.body.jobs[0].match);

    const filtered = await anon('/api/jobs?state=VIC');
    check('state filter works', filtered.body.jobs.every(j => j.state === 'VIC'), filtered.body.total);

    const byType = await anon('/api/jobs?employmentType=Weekend');
    check('employment type filter works',
      byType.body.jobs.every(j => j.employmentType === 'Weekend') && byType.body.total >= 1, byType.body.total);

    const byPay = await anon('/api/jobs?minPay=40');
    check('minimum pay filter works',
      byPay.body.jobs.every(j => (j.payMax || j.payMin) >= 40), byPay.body.total);

    const recent = await anon('/api/jobs?postedWithin=1');
    check('posted-within filter works',
      recent.body.jobs.every(j => Date.now() - new Date(j.createdAt) <= 86400000), recent.body.total);

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

    const fullJob = {
      title: 'Weekend barista', category: 'Hospitality', employmentType: 'Casual',
      state: 'NSW', suburb: 'Newtown', payMin: 33.5, payMax: 38, hoursMin: 12, hoursMax: 18,
      description: 'Saturday and Sunday espresso bar shifts with full training provided.',
      responsibilities: 'Making coffee\nTaking payments',
      requirements: 'Reliable timekeeping\nValid Australian work rights',
      days: ['Sat', 'Sun'], startsOn: '2026-09-01', closesOn: '2026-09-20'
    };

    const underpaid = await employer('/api/jobs', { body: { ...fullJob, payMin: 12, payMax: 15 } });
    check('below-minimum pay is blocked', underpaid.status === 400, underpaid.body);

    const badRange = await employer('/api/jobs', { body: { ...fullJob, payMin: 35, payMax: 30 } });
    check('inverted pay range is blocked', badRange.status === 400, badRange.body);

    const badType = await employer('/api/jobs', { body: { ...fullJob, employmentType: 'Full-time' } });
    check('unknown employment type is blocked', badType.status === 400, badType.body);

    const posted = await employer('/api/jobs', { body: fullJob });
    check('employer can post a job', posted.status === 201, posted.body);
    const jobId = posted.body.job && posted.body.job.id;
    check('job keeps its pay and hours ranges',
      posted.body.job.payMin === 33.5 && posted.body.job.payMax === 38
      && posted.body.job.hoursMin === 12 && posted.body.job.hoursMax === 18, posted.body.job);
    check('job keeps its rostered days',
      JSON.stringify(posted.body.job.days) === JSON.stringify(['Sat', 'Sun']), posted.body.job.days);

    /* social share pack */
    const social = await anon(`/api/social?id=${jobId}`);
    check('share pack builds a caption',
      social.body.post.caption.includes('NOW HIRING')
      && social.body.post.caption.includes('Weekend barista'), social.body.post && social.body.post.caption);
    check('share pack tags the right city',
      social.body.post.hashtags.includes('#sydneyjobs')
      && social.body.post.hashtags.includes('#studentjobs'), social.body.post && social.body.post.hashtags);
    check('share pack writes a Reel script',
      social.body.reel.scenes.length === 4 && social.body.reel.lengthSeconds === 15, social.body.reel);
    check('share pack carries the render fields',
      social.body.job.pay === '$33.50–38/hr' && social.body.job.location === 'Newtown, NSW', social.body.job);

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
      body: { state: 'NSW', suburb: 'Newtown', categories: ['Hospitality'], hoursPerWeek: 15, studyAt: 'UTS' }
    });
    check('student profile saves', profile.body.user.profile.state === 'NSW', profile.body);

    const studentBoard = await student('/api/jobs');
    const match = studentBoard.body.jobs.find(j => j.id === jobId);
    check('matched job scores highly', match && match.match.score >= 90, match && match.match);
    check('best match sorts first', studentBoard.body.jobs[0].id === jobId, studentBoard.body.jobs[0].title);

    check('students cannot post jobs',
      (await student('/api/jobs', { body: { title: 'Nope' } })).status === 403);

    /* saved jobs */
    const save = await student('/api/saved', { body: { jobId } });
    check('student can save a job', save.body.saved === true, save.body);
    const savedList = await student('/api/jobs?saved=true');
    check('saved job appears in the saved list',
      savedList.body.jobs.length === 1 && savedList.body.jobs[0].id === jobId, savedList.body.total);
    const unsave = await student('/api/saved', { body: { jobId } });
    check('saving again removes it', unsave.body.saved === false, unsave.body);
    await student('/api/saved', { body: { jobId } });

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

    /* deleting a job takes its applications with it */
    const throwaway = await employer('/api/jobs', { body: { ...fullJob, title: 'Temporary listing to delete' } });
    const deleted = await employer(`/api/jobs?id=${throwaway.body.job.id}`, { method: 'DELETE' });
    check('employer can delete a listing', deleted.status === 200, deleted.body);
    check('deleted listing is gone',
      (await anon(`/api/jobs?id=${throwaway.body.job.id}`)).status === 404);

    /* pages render */
    for (const page of ['/jobs', '/jobs/browse', '/employer', '/manifest.webmanifest', '/sw.js',
      '/assets/icons/icon-192.png', '/assets/howdy-jobs.css', '/assets/howdy-jobs.js',
      '/assets/howdy-social.js']) {
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
