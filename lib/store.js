/**
 * Howdy Jobs — tiny JSON-file data store.
 *
 * MVP persistence: a single JSON document on disk, loaded once and written
 * back (debounced) on change. On read-only filesystems (Vercel Lambda) it
 * degrades to in-memory so the demo still runs; swap for Postgres/Supabase
 * before real traffic.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_FILE = process.env.HOWDY_DATA_FILE
  || path.join(__dirname, '..', 'data', 'howdy-jobs.json');

const EMPTY = { users: [], jobs: [], applications: [] };

let db = null;
let writable = true;
let writeTimer = null;

function id(prefix) {
  return `${prefix}_${crypto.randomBytes(9).toString('hex')}`;
}

function load() {
  if (db) return db;
  try {
    db = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
    for (const key of Object.keys(EMPTY)) if (!Array.isArray(db[key])) db[key] = [];
  } catch {
    db = JSON.parse(JSON.stringify(EMPTY));
    seed(db);
    persist();
  }
  return db;
}

function persist() {
  if (!writable) return;
  clearTimeout(writeTimer);
  writeTimer = setTimeout(() => {
    try {
      fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
      fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2));
    } catch (err) {
      writable = false;
      console.warn(`[store] filesystem not writable (${err.code}) — running in memory only`);
    }
  }, 25);
}

/* ── seed content ───────────────────────────────────────────────────────── */
// Seeded employers have no password hash, so nobody can sign in as them.
// They exist purely to give a new install a populated job board.
function seed(target) {
  const now = Date.now();
  const day = 86_400_000;

  const employers = [
    ['Bondi Beans Coffee', 'hiring@bondibeans.example', 'NSW', 'Bondi Junction'],
    ['Southbank Grocers', 'jobs@southbankgrocers.example', 'VIC', 'Southbank'],
    ['Riverfront Events Co', 'crew@riverfrontevents.example', 'QLD', 'South Brisbane'],
    ['Adelaide Tutoring Hub', 'team@adelaidetutors.example', 'SA', 'Adelaide'],
    ['Perth Parcel Logistics', 'roster@perthparcel.example', 'WA', 'Osborne Park']
  ].map(([business, email, state, suburb]) => ({
    id: id('usr'),
    role: 'employer',
    name: business,
    email,
    provider: 'seed',
    passwordHash: null,
    createdAt: new Date(now - 30 * day).toISOString(),
    employer: { business, abn: '', website: '', contactPhone: '', state, suburb },
    profile: {}
  }));

  const jobs = [
    {
      e: 0, title: 'Weekend Barista', category: 'Hospitality', jobType: 'Casual',
      payRate: 32.5, hoursPerWeek: 16, suburb: 'Bondi Junction', state: 'NSW',
      description: 'Saturday and Sunday shifts on our espresso bar. Training provided — we just need a friendly face and reliable timekeeping.',
      requirements: 'Barista experience helpful but not essential. Must have valid Australian work rights.'
    },
    {
      e: 0, title: 'Weekday Evening Kitchen Hand', category: 'Hospitality', jobType: 'Casual',
      payRate: 30.2, hoursPerWeek: 12, suburb: 'Surry Hills', state: 'NSW',
      description: 'Evening prep and dishwashing, 5pm–9pm Tuesday to Thursday. Meal included every shift.',
      requirements: 'No experience needed. Comfortable on your feet for four hours.'
    },
    {
      e: 1, title: 'Grocery Shelf Stacker (Early Mornings)', category: 'Retail', jobType: 'Part-time',
      payRate: 29.8, hoursPerWeek: 18, suburb: 'Southbank', state: 'VIC',
      description: '6am–10am weekday shifts restocking shelves before opening. Great fit around afternoon classes.',
      requirements: 'Able to lift 15kg repeatedly. Punctuality is essential.'
    },
    {
      e: 1, title: 'Checkout Assistant', category: 'Retail', jobType: 'Casual',
      payRate: 28.9, hoursPerWeek: 14, suburb: 'Carlton', state: 'VIC',
      description: 'Front-of-store register work across a mix of weekday and weekend shifts.',
      requirements: 'Confident English conversation and basic numeracy.'
    },
    {
      e: 2, title: 'Event Crew — Concerts & Markets', category: 'Events', jobType: 'Casual',
      payRate: 34.0, hoursPerWeek: 10, suburb: 'South Brisbane', state: 'QLD',
      description: 'Bump-in, bar service and pack-down for weekend events along the river precinct.',
      requirements: 'RSA certificate preferred for bar shifts. Weekend availability required.'
    },
    {
      e: 2, title: 'Festival Ticket Scanner', category: 'Events', jobType: 'Casual',
      payRate: 31.0, hoursPerWeek: 8, suburb: 'Gold Coast', state: 'QLD',
      description: 'Gate entry and wristbanding at ticketed events. Short, high-energy shifts.',
      requirements: 'Must be 18+. Comfortable talking to large crowds.'
    },
    {
      e: 3, title: 'High School Maths Tutor', category: 'Tutoring', jobType: 'Part-time',
      payRate: 45.0, hoursPerWeek: 8, suburb: 'Adelaide', state: 'SA',
      description: 'One-on-one Year 9–12 maths tutoring, weekday afternoons at our Adelaide centre.',
      requirements: 'Strong maths results and a Working with Children Check (we help you apply).'
    },
    {
      e: 3, title: 'Online English Conversation Coach', category: 'Tutoring', jobType: 'Casual',
      payRate: 40.0, hoursPerWeek: 6, suburb: 'Remote', state: 'SA',
      description: 'Run 45-minute online conversation sessions with adult learners. Set your own weekly slots.',
      requirements: 'Fluent English, reliable internet, quiet space.'
    },
    {
      e: 4, title: 'Warehouse Parcel Sorter', category: 'Warehouse', jobType: 'Casual',
      payRate: 33.4, hoursPerWeek: 20, suburb: 'Osborne Park', state: 'WA',
      description: 'Evening sort runs, 6pm–10pm. Shifts published a fortnight ahead so you can plan around exams.',
      requirements: 'Steel-cap boots (we reimburse the first pair). Able to lift 20kg.'
    },
    {
      e: 4, title: 'Delivery Driver — Own Vehicle', category: 'Delivery', jobType: 'Casual',
      payRate: 36.0, hoursPerWeek: 15, suburb: 'Perth', state: 'WA',
      description: 'Local parcel runs across the northern suburbs. Kilometre allowance paid on top of the hourly rate.',
      requirements: 'Full or provisional Australian licence, comprehensive insurance, own car.'
    },
    {
      e: 0, title: 'Campus Admin Assistant', category: 'Administration', jobType: 'Part-time',
      payRate: 31.5, hoursPerWeek: 15, suburb: 'Canberra', state: 'ACT',
      description: 'Data entry, reception cover and student enquiry support two days a week.',
      requirements: 'Confident with spreadsheets and email. Prior admin work is a plus.'
    },
    {
      e: 1, title: 'Weekend Cleaner — Serviced Apartments', category: 'Cleaning', jobType: 'Casual',
      payRate: 33.0, hoursPerWeek: 12, suburb: 'Hobart', state: 'TAS',
      description: 'Saturday and Sunday changeover cleans. Equipment and products supplied.',
      requirements: 'Attention to detail. Cleaning experience welcome but not required.'
    },
    {
      e: 2, title: 'Retail Assistant — Airport Newsagency', category: 'Retail', jobType: 'Casual',
      payRate: 32.2, hoursPerWeek: 16, suburb: 'Darwin', state: 'NT',
      description: 'Rotating early and late shifts at the terminal store, seven days a fortnight.',
      requirements: 'Able to pass an aviation security background check.'
    }
  ].map((j, i) => ({
    id: id('job'),
    employerId: employers[j.e].id,
    business: employers[j.e].employer.business,
    title: j.title,
    category: j.category,
    jobType: j.jobType,
    state: j.state,
    suburb: j.suburb,
    payRate: j.payRate,
    payBasis: 'hour',
    hoursPerWeek: j.hoursPerWeek,
    description: j.description,
    requirements: j.requirements,
    closesOn: new Date(now + (14 + i) * day).toISOString().slice(0, 10),
    status: 'open',
    createdAt: new Date(now - (i + 1) * day).toISOString()
  }));

  target.users = employers;
  target.jobs = jobs;
  target.applications = [];
}

/* ── public api ─────────────────────────────────────────────────────────── */
module.exports = {
  id,
  get data() { return load(); },
  users: () => load().users,
  jobs: () => load().jobs,
  applications: () => load().applications,
  save: persist,
  isPersistent: () => writable,
  /** Test helper — drops all state and reseeds. */
  _reset() {
    db = JSON.parse(JSON.stringify(EMPTY));
    seed(db);
    persist();
    return db;
  }
};
