'use strict';

/**
 * Source verification layer.
 *
 * Kip is only allowed to cite domains on this allowlist. After every model
 * response, verifyReply() extracts each URL/domain mentioned, checks it
 * against the allowlist, strips anything unverified, and returns the list
 * of verified sources so the UI can display a "verified sources" panel.
 *
 * This is deterministic server-side code — the model cannot bypass it.
 */

// Wildcard suffixes: any subdomain of these is trusted.
const TRUSTED_SUFFIXES = [
  '.gov.au', // all Australian government sites
  '.edu.au', // all Australian universities
];

// Exact domains (and their subdomains) that are trusted.
const TRUSTED_DOMAINS = new Set([
  // Government (root domains without .gov.au suffix quirks)
  'gov.au',
  'ato.gov.au',
  'fairwork.gov.au',
  'homeaffairs.gov.au',
  'immi.homeaffairs.gov.au',
  'vevo.homeaffairs.gov.au',
  'servicesaustralia.gov.au',
  'studyaustralia.gov.au',
  'moneysmart.gov.au',
  'scamwatch.gov.au',
  'healthdirect.gov.au',
  'mara.gov.au',
  'my.gov.au',
  'transportnsw.info',

  // Property listings (the ONLY housing-search sources Kip may link)
  'realestate.com.au',
  'domain.com.au',
  'flatmates.com.au',

  // OSHC providers (government-approved insurers)
  'medibank.com.au',
  'bupa.com.au',
  'nib.com.au',
  'ahmoshc.com',
  'cbhsinternational.com.au',

  // Major banks
  'commbank.com.au',
  'anz.com.au',
  'westpac.com.au',
  'nab.com.au',

  // Transport authorities not under .gov.au
  'translink.com.au',
  'adelaidemetro.com.au',
  'ptv.vic.gov.au',

  // Student services
  'unidays.com',
  'studentbeans.com',

  // Crisis support
  'lifeline.org.au',
  'beyondblue.org.au',
]);

function normalizeDomain(host) {
  return String(host || '').toLowerCase().replace(/^www\./, '');
}

function isTrustedDomain(host) {
  const domain = normalizeDomain(host);
  if (!domain) return false;
  if (TRUSTED_DOMAINS.has(domain)) return true;
  if (TRUSTED_SUFFIXES.some((s) => domain.endsWith(s))) return true;
  // subdomain of an exact trusted domain (e.g. help.ato.gov.au)
  for (const trusted of TRUSTED_DOMAINS) {
    if (domain.endsWith('.' + trusted)) return true;
  }
  return false;
}

// Matches full URLs and bare domains like "ato.gov.au/path"
const URL_RE =
  /\bhttps?:\/\/[^\s<>()"']+|\b(?:[a-z0-9-]+\.)+(?:gov\.au|edu\.au|com\.au|org\.au|com|info|au)(?:\/[^\s<>()"']*)?/gi;

function extractHost(candidate) {
  try {
    const withScheme = /^https?:\/\//i.test(candidate)
      ? candidate
      : 'https://' + candidate;
    return new URL(withScheme).hostname;
  } catch {
    return '';
  }
}

/**
 * Verify every URL/domain in a model reply against the allowlist.
 * Unverified links are removed; verified ones are collected for the UI.
 *
 * @returns {{ reply: string, sources: Array<{domain: string, url: string}>, verified: boolean }}
 */
function verifyReply(rawReply) {
  const sources = new Map();
  let allVerified = true;

  const reply = String(rawReply).replace(URL_RE, (match) => {
    // Trim trailing punctuation that regex may have captured
    const cleaned = match.replace(/[.,;:!?)\]]+$/, '');
    const host = extractHost(cleaned);
    if (isTrustedDomain(host)) {
      const domain = normalizeDomain(host);
      if (!sources.has(domain)) {
        sources.set(domain, {
          domain,
          url: /^https?:\/\//i.test(cleaned) ? cleaned : 'https://' + cleaned,
        });
      }
      return match;
    }
    allVerified = false;
    return '[link removed — not a verified source]';
  });

  return {
    reply,
    sources: [...sources.values()],
    verified: allVerified,
  };
}

/**
 * Deterministic property-search link builder.
 * Given a location + bedrooms, produce direct search URLs on the trusted
 * listing platforms. Used in the system prompt so Kip never invents
 * individual listings — it always points students to live search results.
 */
function buildListingLinks({ suburb, state = '', postcode = '', bedrooms = '' }) {
  const slug = String(suburb).trim().toLowerCase().replace(/\s+/g, '-');
  const plusSlug = String(suburb).trim().toLowerCase().replace(/\s+/g, '+');
  const st = String(state).trim().toLowerCase();
  const pc = String(postcode).trim();
  const beds = String(bedrooms).trim();

  const links = [];
  const reaLocation = [plusSlug, st, pc].filter(Boolean).join(',+');
  links.push({
    name: 'realestate.com.au',
    url: beds
      ? `https://www.realestate.com.au/rent/property-house-with-${beds}-bedrooms-in-${reaLocation}/list-1`
      : `https://www.realestate.com.au/rent/in-${reaLocation}/list-1`,
  });

  const domainLocation = [slug, st, pc].filter(Boolean).join('-');
  links.push({
    name: 'domain.com.au',
    url: beds
      ? `https://www.domain.com.au/rent/${domainLocation}/?bedrooms=${beds}`
      : `https://www.domain.com.au/rent/${domainLocation}/`,
  });

  links.push({
    name: 'flatmates.com.au',
    url: `https://flatmates.com.au/rooms/${slug}${pc ? '-' + pc : ''}`,
  });

  return links;
}

module.exports = {
  isTrustedDomain,
  verifyReply,
  buildListingLinks,
  TRUSTED_DOMAINS,
  TRUSTED_SUFFIXES,
};
