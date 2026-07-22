'use strict';

/**
 * POST /api/chat — Kip's single conversational endpoint.
 *
 * Request:  { message: string, history?: [{role, content}] }
 * Response: { reply: string, sources: [{domain, url}], verified: boolean }
 *
 * Pipeline (every step is deterministic except the model call):
 *   headers → method check → rate limit → body validation →
 *   PII guard → injection guard → Claude → source verification → respond
 */

const Anthropic = require('@anthropic-ai/sdk');
const config = require('../lib/config');
const security = require('../lib/security');
const { verifyReply } = require('../lib/sources');
const { KIP_SYSTEM } = require('../lib/prompt');

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

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

  // Rate limit
  if (security.isRateLimited(security.clientIp(req))) {
    return res.status(429).json({
      error: 'Too many questions at once — please wait a minute and try again.',
    });
  }

  // Body size + shape validation
  const body = req.body || {};
  if (JSON.stringify(body).length > config.MAX_BODY_BYTES) {
    return res.status(413).json({ error: 'Request too large.' });
  }

  const message = security.sanitizeMessage(body.message);
  if (!message) {
    return res.status(400).json({ error: 'Please type a question.' });
  }

  // PII guard — personal identifiers never reach the model
  if (security.detectPII(message)) {
    return res.status(200).json({
      reply: security.PII_RESPONSE,
      sources: [],
      verified: true,
    });
  }

  // Prompt-injection guard
  if (security.detectInjection(message)) {
    return res.status(200).json({
      reply: security.INJECTION_RESPONSE,
      sources: [],
      verified: true,
    });
  }

  const history = security.sanitizeHistory(body.history);

  try {
    const response = await client.messages.create({
      model: config.MODEL,
      max_tokens: config.MAX_TOKENS,
      system: [
        {
          type: 'text',
          text: KIP_SYSTEM,
          cache_control: { type: 'ephemeral' },
        },
      ],
      messages: [...history, { role: 'user', content: message }],
    });

    const raw = response.content
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('\n');

    // Deterministic server-side source verification — strips any link
    // that is not on the official allowlist.
    const { reply, sources, verified } = verifyReply(raw);

    return res.status(200).json({ reply, sources, verified });
  } catch (err) {
    // Log error class only — never user content
    console.error('[kip-api] error', err.status || err.name || 'unknown');
    return res.status(502).json({
      error: 'Kip is momentarily unavailable. Please try again in a moment.',
    });
  }
};
