const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json({ limit: '16kb' }));

// Security headers on every response
app.use((req, res, next) => {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  if (process.env.NODE_ENV === 'production') {
    res.setHeader('Strict-Transport-Security', 'max-age=63072000; includeSubDomains; preload');
  }
  next();
});

// API routes
app.post('/api/chat', require('./api/chat'));
app.get('/api/health', require('./api/health'));
app.post('/api/subscribe', require('./api/subscribe'));

// Howdy Jobs API
app.get('/api/jobs-config', require('./api/jobs-config'));
app.all('/api/auth', require('./api/auth'));
app.all('/api/jobs', require('./api/jobs'));
app.all('/api/applications', require('./api/applications'));
app.post('/api/saved', require('./api/saved'));

// Static files (index.html, chat.html, etc.)
app.use(express.static(path.join(__dirname), { index: 'index.html' }));

// Page routes
app.get('/chat', (req, res) => res.sendFile(path.join(__dirname, 'chat.html')));
app.get('/jobs', (req, res) => res.sendFile(path.join(__dirname, 'jobs-home.html')));
app.get('/jobs/browse', (req, res) => res.sendFile(path.join(__dirname, 'jobs.html')));
app.get('/employer', (req, res) => res.sendFile(path.join(__dirname, 'employer.html')));
app.get('/ads', (req, res) => res.sendFile(path.join(__dirname, 'ads.html')));
app.get('/', (req, res) => res.sendFile(path.join(__dirname, 'index.html')));

// 404 fallback
app.use((req, res) => res.status(404).sendFile(path.join(__dirname, 'index.html')));

app.listen(PORT, () => {
  console.log(`Howdy running on http://localhost:${PORT}`);
});
