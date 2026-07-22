'use strict';

const knowledge = require('../knowledge/base.json');
const security = require('../lib/security');

module.exports = (req, res) => {
  security.applySecurityHeaders(res);

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed.' });
  }

  return res.status(200).json({
    status: 'ok',
    service: 'Howdy Kip API',
    knowledge_base_version: knowledge._meta.version,
    knowledge_last_updated: knowledge._meta.last_updated,
    timestamp: new Date().toISOString(),
  });
};
