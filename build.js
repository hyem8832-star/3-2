const fs = require('fs');
const path = require('path');

const apiBaseUrl = process.env.API_BASE_URL || 'https://data-ai-assistant-api-3mcf.onrender.com';
const source = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const output = source.replace(
  "'https://data-ai-assistant-api-3mcf.onrender.com'",
  JSON.stringify(apiBaseUrl.replace(/\/$/, '')),
);

fs.mkdirSync(path.join(__dirname, 'dist'), { recursive: true });
fs.writeFileSync(path.join(__dirname, 'dist', 'index.html'), output);
