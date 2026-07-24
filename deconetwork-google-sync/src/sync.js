import { mkdir, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { loadConfig, validateConfig, loadCategoryMap } from './config.js';
import { logger } from './logger.js';
import { getProducts } from './deconetwork.js';
import { validateNormalizedProduct } from './transform.js';
import { buildFeed } from './feed.js';
import { pushProducts, deleteProducts } from './google.js';
import { loadState, saveState, changedSince } from './state.js';
import { renderReport } from './report.js';

async function writeReport(config, summary) {
  if (!config.reportPath) return;
  try {
    await mkdir(dirname(config.reportPath), { recursive: true });
    await writeFile(config.reportPath, renderReport(summary), 'utf8');
    logger.info('Wrote run report', { path: config.reportPath });
  } catch (err) {
    logger.warn('Could not write run report', { error: err.message });
  }
}

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
    const skipSummary = { skipped: true, reason: 'incomplete-config', problems, now };
    await writeReport(config, skipSummary);
    return skipSummary;
  }

  // Enrich config with the (optional) category map before normalization.
  await loadCategoryMap(config);

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

  // Load prior state when either incremental push or stale cleanup is on.
  const usesState = config.incremental || config.cleanupStale;
  const state = usesState ? await loadState(config.statePath) : {};
  const lastSyncAt = state.lastSyncAt;
  // Presence tracking uses ALL extracted ids (not just valid ones) so a
  // product that's still in DecoNetwork but temporarily invalid isn't deleted.
  const currentIds = [...new Set(products.map((p) => p.id).filter(Boolean))];

  // Incremental mode: narrow the push set to products changed since the last
  // successful run. The feed (below) still uses the full valid set.
  const toPush = config.incremental
    ? valid.filter((p) => changedSince(p.modifiedAt, lastSyncAt))
    : valid;
  if (config.incremental) {
    logger.info('Incremental mode', {
      lastSyncAt: lastSyncAt || '(none — full push)',
      changed: toPush.length,
      unchanged: valid.length - toPush.length,
    });
  }

  const summary = {
    now,
    source: config.source,
    syncMode: config.syncMode,
    dryRun: config.dryRun,
    incremental: config.incremental,
    lastSyncAt: lastSyncAt || null,
    extracted: products.length,
    valid: valid.length,
    invalid: invalid.length,
    toPush: toPush.length,
    invalidSamples: invalid.slice(0, 10),
    feed: null,
    push: null,
    cleanup: null,
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
    const result = await pushProducts(config, toPush);
    summary.push = result;

    // A systemic failure (every product failed) is a real error worth a
    // non-zero exit; partial failures are logged but don't sink the run.
    if (!config.dryRun && toPush.length > 0 && result.failed === toPush.length) {
      const err = new Error(
        `All ${toPush.length} product pushes failed — treating as systemic failure`
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

  // 5. Stale cleanup (api | both): remove from Google any product we synced
  //    before that is no longer present in DecoNetwork.
  if (config.cleanupStale && (config.syncMode === 'api' || config.syncMode === 'both')) {
    const previousIds = Array.isArray(state.activeIds) ? state.activeIds : [];
    const currentSet = new Set(currentIds);
    const staleIds = previousIds.filter((id) => !currentSet.has(id));

    if (!previousIds.length) {
      logger.info('Cleanup skipped — no prior catalogue recorded yet');
    } else if (staleIds.length === 0) {
      logger.info('Cleanup: nothing stale to remove');
    } else if (staleIds.length > previousIds.length * config.cleanupMaxFraction) {
      // Guard against mass deletion from an incomplete fetch.
      logger.warn('Cleanup skipped — stale set exceeds safety threshold', {
        stale: staleIds.length,
        previous: previousIds.length,
        maxFraction: config.cleanupMaxFraction,
      });
      summary.cleanup = { skipped: true, reason: 'exceeds-safety-threshold', stale: staleIds.length };
    } else {
      const del = await deleteProducts(config, staleIds);
      summary.cleanup = del;
      if (strict && del.failed > 0) {
        const err = new Error(`${del.failed} stale deletion(s) failed (STRICT mode)`);
        err.summary = summary;
        throw err;
      }
    }
  }

  // 6. Persist state. Guard rails:
  //    - never write during a dry run (nothing was actually changed), and
  //    - if any push failed, keep the previous watermark so the changed set
  //      (including the failures) is retried next run rather than skipped.
  if (usesState && !config.dryRun) {
    const hadFailures = (summary.push?.failed ?? 0) > 0;
    // Only record the catalogue snapshot if the fetch looked complete enough
    // to trust — never overwrite a known catalogue with an empty one.
    const activeIds = currentIds.length ? currentIds : (state.activeIds || []);
    await saveState(config.statePath, {
      lastSyncAt: hadFailures ? (lastSyncAt || null) : now,
      activeIds,
      lastRun: {
        at: now,
        extracted: summary.extracted,
        pushed: summary.push?.succeeded ?? 0,
        failed: summary.push?.failed ?? 0,
        deleted: summary.cleanup?.deleted ?? 0,
        advancedWatermark: !hadFailures,
      },
    });
  }

  await writeReport(config, summary);

  logger.info('Sync finished', {
    extracted: summary.extracted,
    valid: summary.valid,
    invalid: summary.invalid,
    pushed: summary.push?.succeeded ?? 0,
    pushFailed: summary.push?.failed ?? 0,
  });

  return summary;
}
