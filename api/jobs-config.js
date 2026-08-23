/**
 * Howdy Jobs — public front-end configuration (reference lists, feature flags).
 */
const {
  STATES, CATEGORIES, JOB_TYPES, MIN_HOURLY, STUDENT_VISA_FORTNIGHT_HOURS, json, fail
} = require('../lib/jobs-core');
const store = require('../lib/store');

module.exports = (req, res) => {
  if (req.method !== 'GET') return fail(res, 405, 'Method not allowed.');
  json(res, 200, {
    states: STATES,
    categories: CATEGORIES,
    jobTypes: JOB_TYPES,
    minHourly: MIN_HOURLY,
    studentVisaFortnightHours: STUDENT_VISA_FORTNIGHT_HOURS,
    googleClientId: process.env.GOOGLE_CLIENT_ID || null,
    persistentStorage: store.isPersistent()
  });
};
