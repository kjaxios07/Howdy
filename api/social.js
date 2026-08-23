/**
 * Howdy Jobs — social share pack.
 *
 *   GET /api/social?id=job_xxx
 *
 * Turns a listing into everything a business needs to promote it on Instagram:
 * a written caption, Australian hashtags, alt text, a 15-second Reel script,
 * and the fields the browser uses to draw the 1080x1080 post and 1080x1920
 * story/Reel cover. Generated from the job itself — no AI, no external calls.
 */
const store = require('../lib/store');
const { json, fail, payLabel, hoursLabel } = require('../lib/jobs-core');

const query = req => (req.query && Object.keys(req.query).length)
  ? req.query
  : Object.fromEntries(new URL(req.url, 'http://x').searchParams);

// Biggest local hiring hashtag per state, so a Brisbane cafe reaches Brisbane.
const CITY_TAG = {
  NSW: 'sydneyjobs', VIC: 'melbournejobs', QLD: 'brisbanejobs', WA: 'perthjobs',
  SA: 'adelaidejobs', TAS: 'hobartjobs', ACT: 'canberrajobs', NT: 'darwinjobs'
};

const CATEGORY_TAG = {
  'Hospitality': 'hospitalityjobs',
  'Retail': 'retailjobs',
  'Warehouse & Logistics': 'warehousejobs',
  'Delivery & Driving': 'deliveryjobs',
  'Cleaning': 'cleaningjobs',
  'Customer Service': 'customerservicejobs',
  'Administration': 'adminjobs',
  'Events & Promotions': 'eventjobs',
  'Tutoring & Education': 'tutoringjobs',
  'Childcare': 'childcarejobs',
  'Aged Care & Disability': 'agedcarejobs',
  'Healthcare': 'healthcarejobs',
  'Construction & Trades': 'tradesjobs',
  'Farm & Agriculture': 'farmwork',
  'Security': 'securityjobs',
  'IT & Tech Support': 'itjobs',
  'Other': 'localjobs'
};

const CATEGORY_EMOJI = {
  'Hospitality': '🍕',
  'Retail': '🛍️',
  'Warehouse & Logistics': '📦',
  'Delivery & Driving': '🚗',
  'Cleaning': '🧽',
  'Customer Service': '💬',
  'Administration': '🗂️',
  'Events & Promotions': '🎪',
  'Tutoring & Education': '📚',
  'Childcare': '🧸',
  'Aged Care & Disability': '💜',
  'Healthcare': '🩺',
  'Construction & Trades': '🔨',
  'Farm & Agriculture': '🌾',
  'Security': '🛡️',
  'IT & Tech Support': '💻',
  'Other': '✨'
};

const slug = value => String(value || '').toLowerCase().replace(/[^a-z0-9]/g, '');

function hashtags(job) {
  const tags = [
    CITY_TAG[job.state] || 'australianjobs',
    'studentjobs',
    job.employmentType === 'Part-time' ? 'parttimejobs' : 'casualjobs',
    CATEGORY_TAG[job.category] || 'localjobs',
    slug(job.suburb),
    `${slug(job.state)}jobs`,
    'internationalstudents',
    'nowhiring',
    'jobsnearme',
    'howdyjobs'
  ];
  return [...new Set(tags.filter(Boolean))].map(t => `#${t}`);
}

function caption(job) {
  const emoji = CATEGORY_EMOJI[job.category] || '✨';
  const bits = [payLabel(job), job.employmentType, hoursLabel(job)].filter(Boolean).join(' · ');
  const firstLine = String(job.description || '').split('\n')[0].trim();
  const blurb = firstLine.length > 180 ? `${firstLine.slice(0, 177)}…` : firstLine;

  return [
    `${emoji} NOW HIRING — ${job.title}`,
    '',
    `📍 ${job.suburb}, ${job.state}`,
    `💰 ${bits}`,
    '',
    blurb,
    '',
    'Students — apply in two minutes on Howdy Jobs. Link in bio 👆',
    '',
    hashtags(job).join(' ')
  ].join('\n');
}

function reelScript(job) {
  const pay = payLabel(job);
  return {
    hook: `We're hiring a ${job.title} in ${job.suburb} 👀`,
    lengthSeconds: 15,
    scenes: [
      {
        seconds: '0-3',
        shot: 'Front camera, you or a staff member at the venue',
        onScreen: `NOW HIRING: ${job.title}`,
        say: `Hey ${job.suburb} students — we need a ${job.title.toLowerCase()}.`
      },
      {
        seconds: '3-8',
        shot: 'Quick pan of the workspace — the bar, floor, kitchen or dock',
        onScreen: `${pay} · ${job.employmentType}`,
        say: `${pay}, ${hoursLabel(job) || 'flexible hours'}, shifts that fit around class.`
      },
      {
        seconds: '8-12',
        shot: 'Team working, smiling, two or three fast cuts',
        onScreen: job.days && job.days.length ? job.days.join(' · ') : 'Flexible shifts',
        say: 'Full training, friendly team, no experience needed.'
      },
      {
        seconds: '12-15',
        shot: 'Back to camera, point at the caption',
        onScreen: 'APPLY — link in bio',
        say: 'Tap the link in our bio and apply in two minutes.'
      }
    ],
    audioTip: 'Use a trending audio under 20 seconds and keep captions on — most people watch on mute.',
    postingTip: 'Reels posted weekday evenings (6–9pm) reach students when they are actually on their phones.'
  };
}

module.exports = (req, res) => {
  if (req.method !== 'GET') return fail(res, 405, 'Method not allowed.');

  const q = query(req);
  const job = store.jobs().find(j => j.id === q.id);
  if (!job) return fail(res, 404, 'That job is no longer listed.');

  json(res, 200, {
    job: {
      id: job.id,
      title: job.title,
      business: job.business,
      category: job.category,
      employmentType: job.employmentType,
      location: `${job.suburb}, ${job.state}`,
      pay: payLabel(job),
      hours: hoursLabel(job),
      days: job.days || [],
      emoji: CATEGORY_EMOJI[job.category] || '✨',
      verified: !!job.verified
    },
    post: {
      caption: caption(job),
      hashtags: hashtags(job),
      alt: `Now hiring: ${job.title} at ${job.business} in ${job.suburb}, ${job.state}. `
        + `${payLabel(job)}, ${job.employmentType}. Apply on Howdy Jobs.`
    },
    reel: reelScript(job)
  });
};
