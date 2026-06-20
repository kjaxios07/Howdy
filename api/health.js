const knowledge = require('../knowledge/base.json');

module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  res.status(200).json({
    status: 'ok',
    service: 'Howdy Kip API',
    knowledge_base_version: knowledge._meta.version,
    knowledge_last_updated: knowledge._meta.last_updated,
    timestamp: new Date().toISOString()
  });
};
