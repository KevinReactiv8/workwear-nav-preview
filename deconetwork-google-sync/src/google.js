import { readFile } from 'node:fs/promises';
import { logger } from './logger.js';
import { withRetry, isTransientError } from './retry.js';
import { toMerchantProductInput } from './transform.js';

// Build a GoogleAuth instance from either inline service-account JSON or a key
// file path. Scope `content` covers Merchant API product operations.
async function buildAuth(config) {
  const { GoogleAuth } = await import('google-auth-library');
  const scopes = ['https://www.googleapis.com/auth/content'];

  if (config.google.serviceAccountJson) {
    let credentials;
    try {
      credentials = JSON.parse(config.google.serviceAccountJson);
    } catch (err) {
      throw new Error(`GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: ${err.message}`);
    }
    return new GoogleAuth({ credentials, scopes });
  }
  if (config.google.serviceAccountFile) {
    return new GoogleAuth({ keyFilename: config.google.serviceAccountFile, scopes });
  }
  throw new Error('No Google service-account credentials configured');
}

/**
 * Create a Merchant API ProductInputs client. Returns an object with an
 * `insert(productInput)` method and the resolved account/dataSource refs.
 */
export async function createGoogleClient(config) {
  const auth = await buildAuth(config);

  let ProductInputsServiceClient;
  try {
    ({ ProductInputsServiceClient } = (await import('@google-shopping/products')).v1);
  } catch (err) {
    throw new Error(
      "Google Merchant API client not available. Run 'npm install' in " +
      `deconetwork-google-sync/ to install @google-shopping/products. (${err.message})`
    );
  }

  const client = new ProductInputsServiceClient({ auth });
  const parent = `accounts/${config.google.merchantId}`;
  const dataSource = `accounts/${config.google.merchantId}/dataSources/${config.google.dataSourceId}`;

  return {
    async insert(productInput) {
      return withRetry(
        async () => {
          const [result] = await client.insertProductInput({ parent, dataSource, productInput });
          return result;
        },
        { label: `insert ${productInput.offerId}`, shouldRetry: isTransientError }
      );
    },
    parent,
    dataSource,
  };
}

// Run tasks with a bounded concurrency pool.
async function mapWithConcurrency(items, limit, worker) {
  const results = new Array(items.length);
  let cursor = 0;
  async function run() {
    while (cursor < items.length) {
      const index = cursor++;
      results[index] = await worker(items[index], index);
    }
  }
  const pool = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, run);
  await Promise.all(pool);
  return results;
}

/**
 * Push normalized products to Google Merchant Center via the Merchant API.
 * Never throws on a single-product failure — collects per-product outcomes so
 * one bad product cannot fail the whole 24h run.
 *
 * @returns {Promise<{succeeded: number, failed: number, failures: Array<{id:string, error:string}>}>}
 */
export async function pushProducts(config, products) {
  if (config.dryRun) {
    logger.info('DRY_RUN enabled — not calling the Merchant API', { count: products.length });
    return { succeeded: 0, failed: 0, failures: [], skipped: products.length };
  }

  const client = await createGoogleClient(config);
  logger.info('Pushing products to Google Merchant API', {
    count: products.length,
    account: config.google.merchantId,
    concurrency: config.google.concurrency,
  });

  let succeeded = 0;
  const failures = [];

  await mapWithConcurrency(products, config.google.concurrency, async (product) => {
    const input = toMerchantProductInput(product, config);
    try {
      await client.insert(input);
      succeeded += 1;
    } catch (err) {
      failures.push({ id: product.id, error: err?.message || String(err) });
      logger.error('Failed to push product', { id: product.id, error: err?.message || String(err) });
    }
  });

  logger.info('Merchant API push complete', { succeeded, failed: failures.length });
  return { succeeded, failed: failures.length, failures };
}

// Exposed for tests / callers that want to preview the request bodies.
export function buildProductInputs(config, products) {
  return products.map((p) => toMerchantProductInput(p, config));
}
