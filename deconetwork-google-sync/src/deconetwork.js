import { readFile } from 'node:fs/promises';
import { logger } from './logger.js';
import { withRetry, isTransientError } from './retry.js';
import { normalizeDecoNetworkProduct } from './transform.js';

// DecoNetwork wraps every response in a `response_status` object. code 10001
// means success; anything >= 30001 is an error/warning.
function assertOk(body) {
  const status = body?.response_status;
  if (!status) return; // some deployments omit it — be lenient
  const code = Number(status.code);
  if (status.severity === 'ERROR' || (Number.isFinite(code) && code >= 30001)) {
    const err = new Error(
      `DecoNetwork API error ${status.code}: ${status.description || status.severity || 'unknown'}`
    );
    // Auth/permission errors should not be retried.
    err.status = code >= 30001 && code < 40000 ? 401 : 500;
    throw err;
  }
}

// Extract the product array from a response body that may wrap it under a
// variety of keys, or be a bare array.
function extractProducts(body) {
  if (Array.isArray(body)) return body;
  if (!body || typeof body !== 'object') return [];
  for (const key of ['products', 'data', 'items', 'results', 'records', 'rows']) {
    if (Array.isArray(body[key])) return body[key];
  }
  if (body.data && Array.isArray(body.data.products)) return body.data.products;
  if (body.response && Array.isArray(body.response.products)) return body.response.products;
  return [];
}

// Total row count reported by DecoNetwork, if present.
function totalCount(body) {
  const t = body?.total ?? body?.total_count ?? body?.totalCount ?? body?.response?.total;
  return typeof t === 'number' ? t : undefined;
}

async function fetchPage(config, offset) {
  const { baseUrl, productsPath, pageSize, username, password } = config.deconetwork;
  const url = new URL(productsPath, baseUrl + '/').toString();

  // DecoNetwork accepts credentials + params as form-encoded POST body.
  const form = new URLSearchParams();
  form.set('username', username);
  form.set('password', password);
  form.set('offset', String(offset));
  form.set('limit', String(pageSize));
  form.set('per_page', String(pageSize));

  return withRetry(
    async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000);
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: form.toString(),
          signal: controller.signal,
        });
        if (!res.ok) {
          const text = await res.text().catch(() => '');
          const err = new Error(
            `DecoNetwork HTTP ${res.status} ${res.statusText}: ${text.slice(0, 300)}`
          );
          err.status = res.status;
          throw err;
        }
        const body = await res.json();
        assertOk(body);
        return body;
      } finally {
        clearTimeout(timeout);
      }
    },
    { label: `DecoNetwork offset ${offset}`, shouldRetry: isTransientError }
  );
}

/**
 * Fetch and normalize every product from the DecoNetwork store, paging with
 * offset until exhausted. Returns an array of normalized products.
 */
export async function fetchDecoNetworkProducts(config) {
  const raw = [];
  const pageSize = config.deconetwork.pageSize;
  let offset = 0;
  let total;
  const maxOffset = 1_000_000; // runaway guard

  while (offset <= maxOffset) {
    logger.info('Fetching DecoNetwork products', { offset, pageSize });
    const body = await fetchPage(config, offset);
    const page = extractProducts(body);
    if (total === undefined) total = totalCount(body);
    if (!page.length) break;

    if (offset === 0) logDiagnostics(page[0], config);

    raw.push(...page);

    if (total !== undefined) {
      if (raw.length >= total) break;
    } else if (page.length < pageSize) {
      break; // short page => last page
    }
    offset += pageSize;
  }

  logger.info('Fetched raw DecoNetwork products', { count: raw.length, reportedTotal: total });
  return raw.map((r) => normalizeDecoNetworkProduct(r, config));
}

// One-time diagnostic on the first product: surface the real field names and a
// normalized preview so the live mapping can be confirmed from the run logs.
function logDiagnostics(rawProduct, config) {
  if (!config.diagnose || !rawProduct) return;
  logger.info('DIAGNOSE: raw product field names', { keys: Object.keys(rawProduct) });
  logger.info('DIAGNOSE: raw product sample', {
    sample: JSON.stringify(rawProduct).slice(0, 2000),
  });
  const preview = normalizeDecoNetworkProduct(rawProduct, config);
  logger.info('DIAGNOSE: normalized preview', {
    id: preview.id, title: preview.title, price: preview.price,
    link: preview.link, imageLink: preview.imageLink,
    availability: preview.availability, brand: preview.brand,
    googleProductCategory: preview.googleProductCategory,
  });
}

/** Load products from a bundled fixture file (used for demos/tests/dry runs). */
export async function loadFixtureProducts(config) {
  const path = config.fixturePath;
  logger.info('Loading products from fixture', { path });
  const text = await readFile(path, 'utf8');
  const body = JSON.parse(text);
  const raw = extractProducts(body);
  logDiagnostics(raw[0], config);
  return raw.map((r) => normalizeDecoNetworkProduct(r, config));
}

/** Dispatch to the configured product source. */
export async function getProducts(config) {
  if (config.source === 'fixture') return loadFixtureProducts(config);
  return fetchDecoNetworkProducts(config);
}
