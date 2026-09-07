#!/usr/bin/env node
/** Thin JSON-over-stdin adapter for @vercel/blob. Secrets are read only from env. */
import { readFile } from 'node:fs/promises';
import { del, head, list, put } from '@vercel/blob';

const token = process.env.BLOB_READ_WRITE_TOKEN;
if (!token) {
  process.stderr.write('blob_transport_error code=missing_token message=BLOB_READ_WRITE_TOKEN_is_not_set\n');
  process.exit(2);
}

function safeError(error) {
  let message = String(error?.message || error || 'unknown error');
  if (token) message = message.split(token).join('[REDACTED]');
  return {
    ok: false,
    code: String(error?.code || error?.name || 'blob_error'),
    status: Number(error?.status || error?.statusCode || error?.cause?.status || 0) || null,
    message: message.slice(0, 500),
  };
}

async function readRequest() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

try {
  const request = await readRequest();
  let result;
  if (request.op === 'head') {
    result = await head(request.url, { token });
  } else if (request.op === 'put') {
    const body = await readFile(request.file);
    result = await put(request.pathname, body, {
      access: 'public',
      token,
      addRandomSuffix: false,
      allowOverwrite: Boolean(request.allowOverwrite),
      ...(request.ifMatch ? { ifMatch: request.ifMatch } : {}),
      contentType: 'application/json',
      cacheControlMaxAge: Number(request.cacheControlMaxAge),
      multipart: body.length >= 4_000_000,
    });
  } else if (request.op === 'list') {
    const response = await list({
      token,
      prefix: request.prefix,
      limit: Math.min(Number(request.limit || 1000), 1000),
      ...(request.cursor ? { cursor: request.cursor } : {}),
    });
    result = response;
  } else if (request.op === 'delete') {
    await del(request.urls, { token });
    result = { deleted: Array.isArray(request.urls) ? request.urls.length : 1 };
  } else {
    throw Object.assign(new Error('unsupported operation'), { code: 'bad_request' });
  }
  process.stdout.write(`${JSON.stringify({ ok: true, result })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify(safeError(error))}\n`);
  process.exit(1);
}
