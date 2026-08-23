/**
 * Howdy Jobs — starter content so a fresh install has a populated board.
 *
 * Seeded employers have no password hash, so nobody can sign in as them.
 */
const crypto = require('crypto');

const id = prefix => `${prefix}_${crypto.randomBytes(9).toString('hex')}`;

const EMPLOYERS = [
  ['Mozza Pizza & Pasta', 'hiring@mozza.example', 'QLD', 'Coorparoo', 'Hospitality', true],
  ['Bondi Beans Coffee', 'jobs@bondibeans.example', 'NSW', 'Bondi Junction', 'Hospitality', true],
  ['Southbank Grocers', 'careers@southbankgrocers.example', 'VIC', 'Southbank', 'Retail', true],
  ['Riverfront Events Co', 'crew@riverfrontevents.example', 'QLD', 'South Brisbane', 'Events & Promotions', false],
  ['Perth Parcel Logistics', 'roster@perthparcel.example', 'WA', 'Osborne Park', 'Warehouse & Logistics', true],
  ['Adelaide Tutoring Hub', 'team@adelaidetutors.example', 'SA', 'Adelaide', 'Tutoring & Education', false]
];

const JOBS = [
  {
    e: 0, title: 'Kitchen Hand', category: 'Hospitality', employmentType: 'Casual',
    state: 'QLD', suburb: 'Coorparoo', payMin: 30, payMax: 35, hoursMin: 10, hoursMax: 20,
    description: 'We are looking for a casual kitchen hand to join our team on Friday to Sunday evenings. Busy but friendly kitchen, family run for twelve years.',
    responsibilities: 'Food preparation\nCleaning and dishwashing\nAssisting the chefs during service\nHelping close the kitchen down',
    requirements: 'Previous experience preferred but not essential\nWeekend evening availability\nGood communication\nValid Australian work rights',
    days: ['Fri', 'Sat', 'Sun'], startsOn: 14, closesOn: 21
  },
  {
    e: 0, title: 'Pizza Maker', category: 'Hospitality', employmentType: 'Part-time',
    state: 'QLD', suburb: 'Coorparoo', payMin: 32, payMax: 38, hoursMin: 15, hoursMax: 25,
    description: 'Stretch, top and fire our sourdough pizzas across four evening services a week. Full training on our deck ovens.',
    responsibilities: 'Dough and topping prep\nMaking pizzas to order during service\nKeeping the pizza station clean',
    requirements: 'Hospitality experience helpful\nAble to work at pace during a rush\nAvailable at least three evenings a week',
    days: ['Thu', 'Fri', 'Sat', 'Sun'], startsOn: 7, closesOn: 20
  },
  {
    e: 0, title: 'Delivery Driver — Own Car', category: 'Delivery & Driving', employmentType: 'Casual',
    state: 'QLD', suburb: 'Coorparoo', payMin: 31, payMax: 36, hoursMin: 8, hoursMax: 16,
    description: 'Evening deliveries within five kilometres of the shop. Kilometre allowance paid on top of the hourly rate.',
    responsibilities: 'Delivering orders on time\nHandling card and cash payments\nKeeping your vehicle clean and roadworthy',
    requirements: 'Full or provisional Australian licence\nComprehensive insurance\nOwn reliable vehicle',
    days: ['Fri', 'Sat', 'Sun'], startsOn: 10, closesOn: 24
  },
  {
    e: 1, title: 'Weekend Barista', category: 'Hospitality', employmentType: 'Weekend',
    state: 'NSW', suburb: 'Bondi Junction', payMin: 32.5, payMax: 36, hoursMin: 12, hoursMax: 18,
    description: 'Saturday and Sunday shifts on our espresso bar. Training provided — we just need a friendly face and reliable timekeeping.',
    responsibilities: 'Making coffee to order\nTaking orders and payments\nOpening or closing the bar',
    requirements: 'Barista experience helpful but not essential\nValid Australian work rights',
    days: ['Sat', 'Sun'], startsOn: 7, closesOn: 18
  },
  {
    e: 1, title: 'Evening Cafe All-Rounder', category: 'Hospitality', employmentType: 'Evening',
    state: 'NSW', suburb: 'Surry Hills', payMin: 30.2, payMax: 33, hoursMin: 8, hoursMax: 14,
    description: 'Evening prep, service and dishwashing, 5pm to 9pm Tuesday to Thursday. Meal included every shift.',
    responsibilities: 'Prep and plating\nDishwashing\nTable service and clean-down',
    requirements: 'No experience needed\nComfortable on your feet for four hours',
    days: ['Tue', 'Wed', 'Thu'], startsOn: 5, closesOn: 16
  },
  {
    e: 2, title: 'Grocery Shelf Stacker (Early Mornings)', category: 'Retail', employmentType: 'Part-time',
    state: 'VIC', suburb: 'Southbank', payMin: 29.8, payMax: 32, hoursMin: 15, hoursMax: 20,
    description: '6am to 10am weekday shifts restocking shelves before opening. A great fit around afternoon classes.',
    responsibilities: 'Restocking and facing shelves\nBreaking down pallets\nRotating stock by date',
    requirements: 'Able to lift 15kg repeatedly\nPunctuality is essential',
    days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], startsOn: 7, closesOn: 21
  },
  {
    e: 2, title: 'Checkout Assistant', category: 'Customer Service', employmentType: 'Casual',
    state: 'VIC', suburb: 'Carlton', payMin: 28.9, payMax: 31, hoursMin: 10, hoursMax: 18,
    description: 'Front-of-store register work across a mix of weekday and weekend shifts.',
    responsibilities: 'Serving customers at the register\nBagging and trolley collection\nBasic stock questions',
    requirements: 'Confident English conversation\nBasic numeracy',
    days: ['Mon', 'Wed', 'Fri', 'Sat'], startsOn: 3, closesOn: 19
  },
  {
    e: 2, title: 'Store Cleaner — Nights', category: 'Cleaning', employmentType: 'Casual',
    state: 'VIC', suburb: 'Southbank', payMin: 33, payMax: 35, hoursMin: 8, hoursMax: 12,
    description: 'Post-close cleaning of the shop floor and back of house, three nights a week. Equipment and products supplied.',
    responsibilities: 'Floor cleaning and mopping\nBathroom and bin duties\nRestocking consumables',
    requirements: 'Attention to detail\nAble to work unsupervised',
    days: ['Mon', 'Wed', 'Fri'], startsOn: 5, closesOn: 22
  },
  {
    e: 3, title: 'Event Crew — Concerts & Markets', category: 'Events & Promotions', employmentType: 'Casual',
    state: 'QLD', suburb: 'South Brisbane', payMin: 34, payMax: 40, hoursMin: 6, hoursMax: 14,
    description: 'Bump-in, bar service and pack-down for weekend events along the river precinct.',
    responsibilities: 'Setting up and packing down stalls\nBar and food service\nCustomer wayfinding',
    requirements: 'RSA certificate preferred for bar shifts\nWeekend availability\nMust be 18+',
    days: ['Fri', 'Sat', 'Sun'], startsOn: 9, closesOn: 25
  },
  {
    e: 3, title: 'Festival Ticket Scanner', category: 'Events & Promotions', employmentType: 'Temporary',
    state: 'QLD', suburb: 'Gold Coast', payMin: 31, payMax: 33, hoursMin: 6, hoursMax: 10,
    description: 'Gate entry and wristbanding at ticketed events. Short, high-energy shifts across a three-week festival run.',
    responsibilities: 'Scanning tickets at the gate\nIssuing wristbands\nDirecting patrons',
    requirements: 'Must be 18+\nComfortable talking to large crowds',
    days: ['Sat', 'Sun'], startsOn: 12, closesOn: 26
  },
  {
    e: 4, title: 'Warehouse Parcel Sorter', category: 'Warehouse & Logistics', employmentType: 'Casual',
    state: 'WA', suburb: 'Osborne Park', payMin: 33.4, payMax: 37, hoursMin: 15, hoursMax: 25,
    description: 'Evening sort runs, 6pm to 10pm. Shifts are published a fortnight ahead so you can plan around exams.',
    responsibilities: 'Sorting parcels by run\nScanning and labelling\nLoading vans',
    requirements: 'Steel-cap boots (we reimburse the first pair)\nAble to lift 20kg',
    days: ['Mon', 'Tue', 'Wed', 'Thu'], startsOn: 4, closesOn: 20
  },
  {
    e: 4, title: 'Forklift Assistant (Trainee)', category: 'Warehouse & Logistics', employmentType: 'Part-time',
    state: 'WA', suburb: 'Perth', payMin: 32, payMax: 35, hoursMin: 16, hoursMax: 24,
    description: 'Support the dock team with inbound freight. We fund your high-risk work licence after three months.',
    responsibilities: 'Unloading and checking freight\nStock put-away\nKeeping the dock tidy',
    requirements: 'Reliable and safety focused\nInterest in getting a forklift licence',
    days: ['Mon', 'Tue', 'Thu', 'Fri'], startsOn: 14, closesOn: 28
  },
  {
    e: 5, title: 'High School Maths Tutor', category: 'Tutoring & Education', employmentType: 'Part-time',
    state: 'SA', suburb: 'Adelaide', payMin: 45, payMax: 55, hoursMin: 6, hoursMax: 10,
    description: 'One-on-one Year 9 to 12 maths tutoring, weekday afternoons at our Adelaide centre.',
    responsibilities: 'Running one-hour tutoring sessions\nSetting and marking practice work\nShort progress notes for parents',
    requirements: 'Strong maths results\nWorking with Children Check (we help you apply)',
    days: ['Mon', 'Tue', 'Wed', 'Thu'], startsOn: 10, closesOn: 24
  },
  {
    e: 5, title: 'Online English Conversation Coach', category: 'Tutoring & Education', employmentType: 'Casual',
    state: 'SA', suburb: 'Adelaide', payMin: 40, payMax: 48, hoursMin: 4, hoursMax: 8,
    description: 'Run 45-minute online conversation sessions with adult learners. Set your own weekly slots.',
    responsibilities: 'Leading conversation sessions\nLight session notes',
    requirements: 'Fluent English\nReliable internet and a quiet space',
    days: ['Tue', 'Thu', 'Sat'], startsOn: 3, closesOn: 30
  },
  {
    e: 1, title: 'Campus Admin Assistant', category: 'Administration', employmentType: 'Part-time',
    state: 'ACT', suburb: 'Canberra', payMin: 31.5, payMax: 34, hoursMin: 12, hoursMax: 16,
    description: 'Data entry, reception cover and student enquiry support two days a week.',
    responsibilities: 'Reception and phone cover\nData entry\nFiling and mail',
    requirements: 'Confident with spreadsheets and email\nPrior admin work is a plus',
    days: ['Tue', 'Thu'], startsOn: 14, closesOn: 27
  },
  {
    e: 2, title: 'Weekend Cleaner — Serviced Apartments', category: 'Cleaning', employmentType: 'Weekend',
    state: 'TAS', suburb: 'Hobart', payMin: 33, payMax: 36, hoursMin: 10, hoursMax: 14,
    description: 'Saturday and Sunday changeover cleans. Equipment and products supplied.',
    responsibilities: 'Full apartment changeover cleans\nLinen changes\nRestocking amenities',
    requirements: 'Attention to detail\nCleaning experience welcome but not required',
    days: ['Sat', 'Sun'], startsOn: 7, closesOn: 23
  },
  {
    e: 3, title: 'Retail Assistant — Airport Newsagency', category: 'Retail', employmentType: 'Casual',
    state: 'NT', suburb: 'Darwin', payMin: 32.2, payMax: 35, hoursMin: 12, hoursMax: 20,
    description: 'Rotating early and late shifts at the terminal store, seven days a fortnight.',
    responsibilities: 'Register and customer service\nStock replenishment\nStore presentation',
    requirements: 'Able to pass an aviation security background check\nFlexible with early starts',
    days: ['Mon', 'Wed', 'Fri', 'Sat', 'Sun'], startsOn: 21, closesOn: 30
  }
];

function seed(target) {
  const now = Date.now();
  const day = 86400000;
  const iso = offsetDays => new Date(now + offsetDays * day).toISOString().slice(0, 10);

  const employers = EMPLOYERS.map(([business, email, state, suburb, industry, verified]) => ({
    id: id('usr'),
    role: 'employer',
    name: business,
    email,
    provider: 'seed',
    passwordHash: null,
    createdAt: new Date(now - 30 * day).toISOString(),
    employer: {
      business, industry, state, suburb,
      abn: '', website: '', contactName: '', contactPhone: '',
      verified, verificationNote: verified ? 'Verified by Howdy' : ''
    },
    profile: {}
  }));

  const jobs = JOBS.map((j, i) => ({
    id: id('job'),
    employerId: employers[j.e].id,
    business: employers[j.e].employer.business,
    verified: employers[j.e].employer.verified,
    title: j.title,
    category: j.category,
    employmentType: j.employmentType,
    state: j.state,
    suburb: j.suburb,
    payMin: j.payMin,
    payMax: j.payMax,
    hoursMin: j.hoursMin,
    hoursMax: j.hoursMax,
    description: j.description,
    responsibilities: j.responsibilities,
    requirements: j.requirements,
    days: j.days,
    startsOn: iso(j.startsOn),
    closesOn: iso(j.closesOn),
    status: 'open',
    createdAt: new Date(now - (i * 8 + 2) * 3600000).toISOString()
  }));

  target.users = employers;
  target.jobs = jobs;
  target.applications = [];
  target.savedJobs = [];
}

module.exports = { seed, id };
