'use strict';

/**
 * POST /api/subscribe — waitlist signup.
 * Validates input, stores nothing server-side for the MVP, logs no PII.
 */

const security = require('../lib/security');

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

module.exports = async (req, res) => {
  security.applySecurityHeaders(res);

  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(204).end();
  }
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed.' });
  }

  const { name, email, module: interest } = req.body || {};

  if (!name || typeof name !== 'string' || name.trim().length < 2) {
    return res.status(400).json({ error: 'Please provide your name.' });
  }
  if (!email || typeof email !== 'string' || !EMAIL_RE.test(email.trim())) {
    return res.status(400).json({ error: 'Please provide a valid email address.' });
  }

  const safeInterest = String(interest || '').trim().substring(0, 100);

  // MVP: no PII is stored or logged. In production, POST to your email
  // service (Resend/Mailchimp) here over HTTPS and nothing else.
  console.log(
    `[waitlist] signup interest="${safeInterest}" at="${new Date().toISOString()}"`
  );

  return res.status(200).json({
    success: true,
    message: "You're on the list! We'll reach out when Kip goes live.",
  });
};
