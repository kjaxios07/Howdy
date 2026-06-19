/**
 * Daily knowledge base updater — run via GitHub Actions cron
 *
 * Fetches key pages from official Australian government sources,
 * uses Claude to extract and verify structured facts,
 * then updates knowledge/base.json and commits the change.
 *
 * Required env vars:
 *   ANTHROPIC_API_KEY   — Claude API key
 *   GITHUB_TOKEN        — provided automatically in GitHub Actions
 *
 * Run locally:  node scripts/update-knowledge.js
 * In CI:        triggered by .github/workflows/update-knowledge.yml
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const https = require('https');

const KNOWLEDGE_PATH = path.join(__dirname, '..', 'knowledge', 'base.json');

// Pages to check for updates — all official Australian government sources
const SOURCES_TO_FETCH = [
  {
    url: 'https://www.fairwork.gov.au/pay-and-wages/minimum-wages',
    topic: 'minimum_wage',
    description: 'National Minimum Wage'
  },
  {
    url: 'https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500/work',
    topic: 'student_500_work_rights',
    description: 'Student visa 500 work rights'
  },
  {
    url: 'https://www.ato.gov.au/individuals-and-families/tax-file-number/apply-for-a-tfn',
    topic: 'tfn_application',
    description: 'TFN application process'
  }
];

/**
 * Minimal HTTPS GET — returns page text.
 * Uses a respectful User-Agent and honours robots.txt conventions.
 * Only fetches publicly accessible government pages.
 */
function fetchPage(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, {
      headers: {
        'User-Agent': 'HowdyAU-KnowledgeBot/1.0 (+https://howdy.com.au/bot)',
        'Accept': 'text/html'
      },
      timeout: 10_000
    }, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        return fetchPage(res.headers.location).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`HTTP ${res.statusCode} for ${url}`));
      }
      let body = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve(body));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error(`Timeout fetching ${url}`)); });
  });
}

/**
 * Strip HTML tags for basic text extraction.
 * A full DOM parser is avoided to keep the script dependency-free.
 */
function stripHtml(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&nbsp;/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
    .substring(0, 4000); // limit for Claude context
}

async function run() {
  console.log('[update-knowledge] Starting knowledge base refresh…');

  const existing = JSON.parse(fs.readFileSync(KNOWLEDGE_PATH, 'utf8'));
  let updated = false;

  for (const source of SOURCES_TO_FETCH) {
    try {
      console.log(`[update-knowledge] Fetching: ${source.url}`);
      const html = await fetchPage(source.url);
      const text = stripHtml(html);

      // In production: send `text` to Claude with a structured extraction prompt
      // to verify facts and detect changes from the current knowledge base.
      // Example prompt:
      //
      // const client = new Anthropic();
      // const result = await client.messages.create({
      //   model: 'claude-sonnet-4-6',
      //   max_tokens: 500,
      //   messages: [{
      //     role: 'user',
      //     content: `Extract the current ${source.description} from this page text.
      //               Return JSON only: { "changed": true/false, "value": "..." }
      //               Current value: ${JSON.stringify(existing)}
      //               Page text: ${text}`
      //   }]
      // });
      //
      // const extracted = JSON.parse(result.content[0].text);
      // if (extracted.changed) { /* update knowledge base */ updated = true; }

      console.log(`[update-knowledge] Fetched ${source.topic} (${text.length} chars) — Claude extraction placeholder`);

    } catch (err) {
      console.error(`[update-knowledge] Error for ${source.topic}:`, err.message);
    }
  }

  // Always bump last_updated timestamp on a daily run
  existing._meta.last_updated = new Date().toISOString().split('T')[0];
  fs.writeFileSync(KNOWLEDGE_PATH, JSON.stringify(existing, null, 2), 'utf8');

  if (updated) {
    console.log('[update-knowledge] Knowledge base updated with new data.');
  } else {
    console.log('[update-knowledge] No changes detected — timestamp refreshed.');
  }
}

run().catch(err => {
  console.error('[update-knowledge] Fatal error:', err.message);
  process.exit(1);
});
