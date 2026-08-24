/**
 * Kip Jobs — CV and application attachments.
 *
 *   POST   /api/files?name=cv.pdf&type=application/pdf   raw bytes, returns metadata
 *   GET    /api/files?id=file_xxx                        download (access-checked)
 *   DELETE /api/files?id=file_xxx                        remove your own file
 *
 * Files are written under the data directory with a random name — never the
 * uploaded one — and are only ever served through this handler, so a CV is
 * readable by the student who owns it and by an employer they applied to.
 * Nothing is web-reachable by path.
 */
const fs = require('fs');
const path = require('path');
const store = require('../lib/store');
const auth = require('../lib/auth');
const { json, fail, csrfOk, clean, rateLimit, clientIp } = require('../lib/jobs-core');

const MAX_BYTES = 10 * 1024 * 1024;

const TYPES = {
  'application/pdf': { ext: 'pdf', kind: 'PDF' },
  'application/msword': { ext: 'doc', kind: 'DOC' },
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': { ext: 'docx', kind: 'DOCX' },
  'image/jpeg': { ext: 'jpg', kind: 'JPG' },
  'image/png': { ext: 'png', kind: 'PNG' }
};

const UPLOAD_DIR = process.env.HOWDY_UPLOAD_DIR
  || path.join(path.dirname(process.env.HOWDY_DATA_FILE
    || path.join(__dirname, '..', 'data', 'howdy-jobs.json')), 'uploads');

const query = req => (req.query && Object.keys(req.query).length)
  ? req.query
  : Object.fromEntries(new URL(req.url, 'http://x').searchParams);

/**
 * Express hands us an already-buffered body (express.raw); a bare Node request
 * still streams. Support both so the handler works either way.
 */
function bytesOf(req) {
  if (Buffer.isBuffer(req.body)) {
    return req.body.length > MAX_BYTES
      ? Promise.reject(new Error('Files must be 10 MB or smaller.'))
      : Promise.resolve(req.body);
  }
  return readBytes(req);
}

function readBytes(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BYTES) {
        reject(new Error('Files must be 10 MB or smaller.'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

/** Who may read this file: its owner, or an employer it was sent to. */
function mayRead(file, user) {
  if (!user) return false;
  if (file.ownerId === user.id) return true;
  if (user.role !== 'employer') return false;

  const myJobs = new Set(store.jobs().filter(j => j.employerId === user.id).map(j => j.id));
  return store.applications().some(app => {
    if (!myJobs.has(app.jobId)) return false;
    const attached = [app.cv].concat(app.attachments || []).filter(Boolean);
    return attached.some(meta => meta.id === file.id);
  });
}

module.exports = async (req, res) => {
  const q = query(req);
  const user = auth.currentUser(req);
  const files = store.files();

  /* ── download ─────────────────────────────────────────────────────────── */
  if (req.method === 'GET') {
    const file = files.find(f => f.id === q.id);
    if (!file) return fail(res, 404, 'That file is no longer stored.');
    if (!mayRead(file, user)) return fail(res, 403, 'You do not have access to that file.');

    let bytes;
    try {
      bytes = fs.readFileSync(path.join(UPLOAD_DIR, file.storedAs));
    } catch {
      return fail(res, 410, 'That file is no longer stored on this server.');
    }

    res.setHeader('Content-Type', file.type);
    res.setHeader('Content-Length', bytes.length);
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    // Always an attachment: never render an upload inline in our own origin.
    res.setHeader('Content-Disposition',
      `attachment; filename="${file.name.replace(/[^\w. -]/g, '_')}"`);
    return res.status(200).end(bytes);
  }

  if (!csrfOk(req)) return fail(res, 403, 'Missing client header.');
  if (!user) return fail(res, 401, 'Please sign in.');

  /* ── upload ───────────────────────────────────────────────────────────── */
  if (req.method === 'POST') {
    if (!rateLimit(`upload:${clientIp(req)}`, 30, 3600000)) {
      return fail(res, 429, 'Too many uploads — try again later.');
    }

    const type = clean(q.type, 120);
    const spec = TYPES[type];
    if (!spec) return fail(res, 415, 'Use a PDF, DOC, DOCX, JPG or PNG file.');

    let bytes;
    try {
      bytes = await bytesOf(req);
    } catch (err) {
      return fail(res, 413, err.message);
    }
    if (!bytes.length) return fail(res, 400, 'That file is empty.');

    const meta = {
      id: store.id('file'),
      ownerId: user.id,
      name: clean(q.name, 120) || `upload.${spec.ext}`,
      type,
      kind: spec.kind,
      size: bytes.length,
      storedAs: `${store.id('blob')}.${spec.ext}`,
      createdAt: new Date().toISOString()
    };

    try {
      fs.mkdirSync(UPLOAD_DIR, { recursive: true });
      fs.writeFileSync(path.join(UPLOAD_DIR, meta.storedAs), bytes);
    } catch (err) {
      console.warn(`[files] cannot write uploads (${err.code})`);
      return fail(res, 507, 'File storage is not writable on this server.');
    }

    files.push(meta);
    store.save();
    return json(res, 201, { file: publicMeta(meta) });
  }

  /* ── delete ───────────────────────────────────────────────────────────── */
  if (req.method === 'DELETE') {
    const at = files.findIndex(f => f.id === q.id);
    if (at === -1) return fail(res, 404, 'File not found.');
    if (files[at].ownerId !== user.id) return fail(res, 403, 'That file belongs to another account.');

    try { fs.unlinkSync(path.join(UPLOAD_DIR, files[at].storedAs)); } catch { /* already gone */ }
    files.splice(at, 1);
    store.save();
    return json(res, 200, { ok: true });
  }

  return fail(res, 405, 'Method not allowed.');
};

/** The shape the front end stores on a profile or an application. */
function publicMeta(meta) {
  return { id: meta.id, name: meta.name, type: meta.type, kind: meta.kind, size: meta.size };
}

module.exports.publicMeta = publicMeta;
module.exports.UPLOAD_DIR = UPLOAD_DIR;
