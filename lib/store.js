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
const { seed, id } = require('./seed');

const DATA_FILE = process.env.HOWDY_DATA_FILE
  || path.join(__dirname, '..', 'data', 'howdy-jobs.json');

const COLLECTIONS = ['users', 'jobs', 'applications', 'savedJobs'];

let db = null;
let writable = true;
let writeTimer = null;

function load() {
  if (db) return db;
  try {
    db = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
    for (const key of COLLECTIONS) if (!Array.isArray(db[key])) db[key] = [];
  } catch {
    db = {};
    for (const key of COLLECTIONS) db[key] = [];
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

module.exports = {
  id,
  get data() { return load(); },
  users: () => load().users,
  jobs: () => load().jobs,
  applications: () => load().applications,
  savedJobs: () => load().savedJobs,
  save: persist,
  isPersistent: () => writable,
  /** Test helper — drops all state and reseeds. */
  _reset() {
    db = {};
    for (const key of COLLECTIONS) db[key] = [];
    seed(db);
    persist();
    return db;
  }
};
