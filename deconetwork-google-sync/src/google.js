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
    async remove(offerId) {
      const name = productInputName(config, offerId);
      return withRetry(
        async () => {
          await client.deleteProductInput({ name, dataSource });
          return true;
        },
        { label: `delete ${offerId}`, shouldRetry: isTransientError }
      );
    },
    parent,
    dataSource,
  };
}

// Merchant API product-input resource name:
//   accounts/{account}/productInputs/{contentLanguage}~{feedLabel}~{offerId}
export function productInputName(config, offerId) {
  const { merchantId, contentLanguage, feedLabel } = config.google;
  return `accounts/${merchantId}/productInputs/${contentLanguage}~${feedLabel}~${offerId}`;
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

/**
 * Delete products from Google Merchant Center by offerId (used to remove
 * listings that no longer exist in DecoNetwork). Per-id error isolation; a
 * "not found" is treated as already-gone (success), not a failure.
 */
export async function deleteProducts(config, offerIds) {
  if (!offerIds.length) return { deleted: 0, failed: 0, failures: [] };
  if (config.dryRun) {
    logger.info('DRY_RUN enabled — not deleting from the Merchant API', { count: offerIds.length });
    return { deleted: 0, failed: 0, failures: [], skipped: offerIds.length };
  }

  const client = await createGoogleClient(config);
  logger.info('Deleting stale products from Google Merchant API', { count: offerIds.length });

  let deleted = 0;
  const failures = [];

  await mapWithConcurrency(offerIds, config.google.concurrency, async (offerId) => {
    try {
      await client.remove(offerId);
      deleted += 1;
    } catch (err) {
      const status = err?.code || err?.status;
      // 5 = NOT_FOUND (gRPC) / 404: the product is already gone — that's fine.
      if (status === 5 || status === 404) {
        deleted += 1;
        return;
      }
      failures.push({ id: offerId, error: err?.message || String(err) });
      logger.error('Failed to delete product', { id: offerId, error: err?.message || String(err) });
    }
  });

  logger.info('Merchant API delete complete', { deleted, failed: failures.length });
  return { deleted, failed: failures.length, failures };
}

// Exposed for tests / callers that want to preview the request bodies.
export function buildProductInputs(config, products) {
  return products.map((p) => toMerchantProductInput(p, config));
}
