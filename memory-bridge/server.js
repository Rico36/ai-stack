const http = require('http');

const port = Number(process.env.PORT || 8787);
const token = process.env.MEMORY_CAPTURE_TOKEN || '';
const webhookUrl = process.env.N8N_MEMORY_WEBHOOK_URL || 'http://n8n:5678/webhook/local-ai/memory-capture';
const maxNoteLength = Number(process.env.MEMORY_BRIDGE_MAX_NOTE_LENGTH || 4000);

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';

    req.on('data', (chunk) => {
      data += chunk;
      if (data.length > maxNoteLength * 4) {
        reject(new Error('Request body too large.'));
        req.destroy();
      }
    });

    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

async function handleSaveMemory(req, res) {
  if (!token) {
    return sendJson(res, 500, { error: 'Bridge is missing MEMORY_CAPTURE_TOKEN.' });
  }

  let parsed;
  try {
    const raw = await readBody(req);
    parsed = raw ? JSON.parse(raw) : {};
  } catch (error) {
    return sendJson(res, 400, { error: 'Invalid JSON request body.' });
  }

  const note = String(parsed.note || parsed.text || '').trim();
  const source = String(parsed.source || 'anythingllm').trim() || 'anythingllm';

  if (!note) {
    return sendJson(res, 400, { error: 'A non-empty note is required.' });
  }

  if (note.length > maxNoteLength) {
    return sendJson(res, 400, { error: `Note is too long. Max length is ${maxNoteLength} characters.` });
  }

  let upstream;
  try {
    upstream = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, note, source }),
    });
  } catch (error) {
    return sendJson(res, 502, { error: 'Failed to reach n8n memory webhook.', details: error.message });
  }

  let responseBody = {};
  try {
    responseBody = await upstream.json();
  } catch (error) {
    responseBody = { raw: await upstream.text().catch(() => '') };
  }

  return sendJson(res, upstream.status, responseBody);
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    return sendJson(res, 200, { status: 'ok' });
  }

  if (req.method === 'POST' && req.url === '/save-memory') {
    return handleSaveMemory(req, res);
  }

  return sendJson(res, 404, { error: 'Not found.' });
});

server.listen(port, '0.0.0.0', () => {
  console.log(`memory-bridge listening on ${port}`);
});
