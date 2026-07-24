import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { loadConfig, validateConfig } from './config.js';
import { logger } from './logger.js';
import { getProducts } from './deconetwork.js';
import { validateNormalizedProduct } from './transform.js';
import { buildFeed } from './feed.js';
import { pushProducts } from './google.js';

/**
 * Run one full sync. Designed to never throw for routine conditions (missing
 * config, individual bad products, individual API failures) so a scheduled run
 * stays green; only genuinely systemic failures surface as a thrown error.
 *
 * @param {object} [options]
 * @param {NodeJS.ProcessEnv} [options.env]
 * @param {string} [options.now] ISO timestamp (injected for deterministic feeds)
 * @returns {Promise<object>} run summary
 */
export async function runSync(options = {}) {
  const env = options.env || process.env;
  const now = options.now || new Date().toISOString();
  const strict = ['1', 'true', 'yes', 'on'].includes(String(env.STRICT || '').toLowerCase());

  const config = loadConfig(env);
  logger.info('Starting DecoNetwork → Google Shopping sync', {
    source: config.source,
    syncMode: config.syncMode,
    dryRun: config.dryRun,
    strict,
  });

  const problems = validateConfig(config);
  if (problems.length) {
    if (strict) {
      throw new Error(`Configuration invalid: ${problems.join('; ')}`);
    }
    // Non-strict: if the live source is unconfigured, skip cleanly rather than
    // fail the scheduled run. This keeps the 24h job error-free until secrets
    // are provided, at which point it starts syncing for real.
    logger.warn('Configuration incomplete — skipping this run (set STRICT=true to fail instead)', {
      problems,
    });
    return { skipped: true, reason: 'incomplete-config', problems, now };
  }

  // 1. Extract products from the source.
  const products = await getProducts(config);
  logger.info('Products extracted', { count: products.length });

  // 2. Validate; drop invalid ones with a warning (one bad product must not
  //    sink the run).
  const valid = [];
  const invalid = [];
  for (const p of products) {
    const issues = validateNormalizedProduct(p);
    if (issues.length) {
      invalid.push({ id: p.id || '(no id)', issues });
      logger.warn('Skipping invalid product', { id: p.id || '(no id)', issues });
    } else {
      valid.push(p);
    }
  }
  logger.info('Product validation complete', { valid: valid.length, invalid: invalid.length });

  const summary = {
    now,
    source: config.source,
    syncMode: config.syncMode,
    dryRun: config.dryRun,
    extracted: products.length,
    valid: valid.length,
    invalid: invalid.length,
    invalidSamples: invalid.slice(0, 10),
    feed: null,
    push: null,
  };

  // 3. Feed output (feed | both).
  if (config.syncMode === 'feed' || config.syncMode === 'both') {
    const xml = buildFeed(valid, {
      title: 'DecoNetwork Product Feed',
      link: config.deconetwork.baseUrl || 'https://www.deconetwork.com',
      description: 'Products synced from DecoNetwork to Google Shopping',
      updated: now,
    });
    await mkdir(dirname(config.feedOutputPath), { recursive: true });
    await writeFile(config.feedOutputPath, xml, 'utf8');
    logger.info('Wrote Google Shopping feed', { path: config.feedOutputPath, items: valid.length });
    summary.feed = { path: config.feedOutputPath, items: valid.length };
  }

  // 4. Merchant API push (api | both).
  if (config.syncMode === 'api' || config.syncMode === 'both') {
    const result = await pushProducts(config, valid);
    summary.push = result;

    // A systemic failure (every product failed) is a real error worth a
    // non-zero exit; partial failures are logged but don't sink the run.
    if (!config.dryRun && valid.length > 0 && result.failed === valid.length) {
      const err = new Error(
        `All ${valid.length} product pushes failed — treating as systemic failure`
      );
      err.summary = summary;
      throw err;
    }
    if (strict && result.failed > 0) {
      const err = new Error(`${result.failed} product push(es) failed (STRICT mode)`);
      err.summary = summary;
      throw err;
    }
  }

  logger.info('Sync finished', {
    extracted: summary.extracted,
    valid: summary.valid,
    invalid: summary.invalid,
    pushed: summary.push?.succeeded ?? 0,
    pushFailed: summary.push?.failed ?? 0,
  });

  return summary;
}
