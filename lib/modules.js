'use strict';

/**
 * The 10 Kip modules — organised around what international students
 * actually ask, in their own words. Each module has:
 *  - id:        stable key (matches knowledge/base.json sections)
 *  - name:      short label shown in the UI
 *  - emoji:     visual anchor
 *  - tagline:   one-line promise
 *  - examples:  real questions students ask (used as chips in the chat UI)
 *  - sources:   the official domains this module cites
 */
module.exports = [
  {
    id: 'arrive',
    name: 'Just Landed',
    emoji: '🛬',
    tagline: 'Your first 30 days in Australia, step by step',
    examples: [
      'What should I do in my first week in Australia?',
      'What documents do I need to set up my life here?',
    ],
    sources: ['studyaustralia.gov.au', 'homeaffairs.gov.au'],
  },
  {
    id: 'visa',
    name: 'Visas & Work Rights',
    emoji: '🛂',
    tagline: 'Student 500, Graduate 485, and how many hours you can work',
    examples: [
      'How many hours can I work on a student visa?',
      'How do I apply for the 485 visa after graduation?',
      'How do I check my visa conditions?',
    ],
    sources: ['immi.homeaffairs.gov.au', 'vevo.homeaffairs.gov.au'],
  },
  {
    id: 'tax',
    name: 'TFN, Tax & Super',
    emoji: '🧾',
    tagline: 'Get your Tax File Number, understand tax and superannuation',
    examples: [
      'How do I apply for a TFN?',
      'What happens if I work without a TFN?',
      'Can I claim my super when I leave Australia?',
    ],
    sources: ['ato.gov.au', 'my.gov.au'],
  },
  {
    id: 'work',
    name: 'Jobs & Pay Rights',
    emoji: '💼',
    tagline: 'Minimum wage, payslips, and what to do if you are underpaid',
    examples: [
      'What is the minimum wage in Australia?',
      'My employer pays me cash below minimum wage — what can I do?',
    ],
    sources: ['fairwork.gov.au'],
  },
  {
    id: 'housing',
    name: 'Housing & Rentals',
    emoji: '🏠',
    tagline: 'Find listings on trusted sites, understand bond and your rights',
    examples: [
      'Two bedroom house near Acacia Ridge 4110 Brisbane',
      'How much bond do I pay and how do I get it back?',
      'What do I need to apply for a rental?',
    ],
    sources: ['realestate.com.au', 'domain.com.au', 'flatmates.com.au'],
  },
  {
    id: 'health',
    name: 'OSHC & Healthcare',
    emoji: '🏥',
    tagline: 'Your health cover, seeing a doctor, and emergency numbers',
    examples: [
      'What does my OSHC actually cover?',
      'Am I eligible for Medicare as a student?',
      'How do I see a doctor without paying a lot?',
    ],
    sources: ['servicesaustralia.gov.au', 'homeaffairs.gov.au', 'healthdirect.gov.au'],
  },
  {
    id: 'money',
    name: 'Banking & Money',
    emoji: '🏦',
    tagline: 'Open a bank account, send money home, avoid bad exchange rates',
    examples: [
      'Which bank account is best for students?',
      'Can I open a bank account before I arrive?',
    ],
    sources: ['moneysmart.gov.au'],
  },
  {
    id: 'transport',
    name: 'Getting Around',
    emoji: '🚋',
    tagline: 'Transport cards, student concessions, city by city',
    examples: [
      'How do I get a student discount on public transport in Brisbane?',
      'What is an Opal card and how do I get the concession?',
    ],
    sources: ['translink.com.au', 'transportnsw.info', 'ptv.vic.gov.au'],
  },
  {
    id: 'study',
    name: 'Student Life & Discounts',
    emoji: '🎓',
    tagline: 'UNiDAYS, cheap groceries, and making the most of student life',
    examples: [
      'What student discounts can I get in Australia?',
      'How much should I budget for groceries each week?',
    ],
    sources: ['unidays.com', 'studentbeans.com', 'studyaustralia.gov.au'],
  },
  {
    id: 'safety',
    name: 'Safety, Scams & Emergencies',
    emoji: '🛡️',
    tagline: 'Emergency numbers, common scams targeting students, mental health support',
    examples: [
      'Someone called saying my visa will be cancelled unless I pay — is this a scam?',
      'What number do I call in an emergency?',
      'Where can I get mental health support as a student?',
    ],
    sources: ['scamwatch.gov.au', 'healthdirect.gov.au', 'lifeline.org.au'],
  },
];
