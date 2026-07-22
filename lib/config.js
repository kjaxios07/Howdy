'use strict';

/**
 * Central configuration for the Howdy / Kip API.
 * Everything tunable lives here so behaviour is auditable in one place.
 */
module.exports = {
  // Claude model — override with KIP_MODEL env var if needed
  // (e.g. KIP_MODEL=claude-sonnet-5 for lower cost per message).
  MODEL: process.env.KIP_MODEL || 'claude-opus-4-8',
  MAX_TOKENS: 700,

  // Input limits
  MAX_MESSAGE_CHARS: 800,
  MAX_HISTORY_TURNS: 8,
  MAX_HISTORY_CHARS: 1500,
  MAX_BODY_BYTES: 32 * 1024, // 32 KB request body cap

  // Rate limiting (per IP, in-memory — swap for Upstash/Vercel KV at scale)
  RATE_LIMIT_MAX: 20,
  RATE_LIMIT_WINDOW_MS: 60_000,
  RATE_LIMIT_MAX_BUCKETS: 8000,
};
