module.exports = async (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');

  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { name, email, module: interest } = req.body || {};

  // Validate name
  if (!name || typeof name !== 'string' || name.trim().length < 2) {
    return res.status(400).json({ error: 'Please provide your full name.' });
  }

  // Validate email format
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!email || typeof email !== 'string' || !emailRegex.test(email.trim())) {
    return res.status(400).json({ error: 'Please provide a valid email address.' });
  }

  // Sanitize inputs
  const safeName = name.trim().substring(0, 100);
  const safeEmail = email.trim().toLowerCase().substring(0, 254);
  const safeInterest = (interest || '').trim().substring(0, 100);

  // Log minimal metadata only — no PII stored server-side for MVP
  // In production: POST to Mailchimp/Resend/ConvertKit API here
  console.log(`[waitlist] new_signup interest="${safeInterest}" timestamp="${new Date().toISOString()}"`);

  // TODO (production): integrate with email service
  // Example: await sendToMailchimp({ email: safeEmail, name: safeName, tags: [safeInterest] });

  return res.status(200).json({
    success: true,
    message: "You're on the list! We'll reach out when Kip goes live."
  });
};
