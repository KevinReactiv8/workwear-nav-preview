// Centralised configuration, sourced from environment variables so the same
// build runs locally, in cron, and in GitHub Actions with only secrets changing.

function bool(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

function num(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function loadConfig(env = process.env) {
  const config = {
    // ---- DecoNetwork (source) ----
    // DecoNetwork exposes a JSON-over-HTTP management API. Products are listed
    // via POST /api/json/manage_products/find, authenticated with the
    // account username + password (Enterprise plan / admin access required).
    deconetwork: {
      // Base URL of the store, e.g. https://mystore.deconetwork.com
      baseUrl: (env.DECONETWORK_API_BASE || '').replace(/\/+$/, ''),
      username: env.DECONETWORK_USERNAME || '',
      password: env.DECONETWORK_PASSWORD || '',
      // Endpoint path is overridable in case DecoNetwork changes it.
      productsPath: env.DECONETWORK_PRODUCTS_PATH || '/api/json/manage_products/find',
      // DecoNetwork caps results at 100 per request; page with offset.
      pageSize: Math.min(num(env.DECONETWORK_PAGE_SIZE, 100), 100),
      // DecoNetwork product pages use a non-standard URL shape:
      //   https://<store>/blank_product/<product_id>/<name-slug>
      // The API returns the id + name but not this URL, so we build it. The
      // pattern is overridable in case a store uses a different segment.
      // Placeholders: {base} {id} {slug}
      productUrlPattern:
        env.DECONETWORK_PRODUCT_URL_PATTERN || '{base}/blank_product/{id}/{slug}',
    },

    // ---- Google Shopping (destination) — Merchant API v1 ----
    google: {
      // Merchant Center account ID (the numeric account id).
      merchantId: env.GOOGLE_MERCHANT_ID || '',
      // API-type data source id created once in Merchant Center. Required by
      // the Merchant API productInputs:insert call.
      dataSourceId: env.GOOGLE_DATA_SOURCE_ID || '',
      // Service-account key: either inline JSON or a path to a JSON file.
      serviceAccountJson: env.GOOGLE_SERVICE_ACCOUNT_JSON || '',
      serviceAccountFile: env.GOOGLE_SERVICE_ACCOUNT_FILE || '',
      contentLanguage: env.GOOGLE_CONTENT_LANGUAGE || 'en',
      // Merchant API groups/targets by feedLabel (usually the destination
      // country code, e.g. GB). Defaults from GOOGLE_TARGET_COUNTRY.
      feedLabel: env.GOOGLE_FEED_LABEL || env.GOOGLE_TARGET_COUNTRY || 'GB',
      // Default Google product category for products missing one.
      defaultProductCategory: env.GOOGLE_DEFAULT_CATEGORY || 'Apparel & Accessories',
      // Path to an editable DecoNetwork→Google category map (loaded at runtime).
      categoryMapPath: env.GOOGLE_CATEGORY_MAP || 'config/google-category-map.json',
      // Populated by loadCategoryMap() before products are normalized.
      categoryMap: null,
      // Concurrency for productInputs:insert calls.
      concurrency: num(env.GOOGLE_CONCURRENCY, 5),
    },

    // ---- Behaviour ----
    // 'api'  -> push to Google Content API for Shopping
    // 'feed' -> write an XML product feed to disk (for scheduled fetch by GMC)
    // 'both' -> do both
    syncMode: (env.SYNC_MODE || 'api').toLowerCase(),
    dryRun: bool(env.DRY_RUN, false),
    // One-time diagnostic: log the raw field names/shape of the first product
    // returned by DecoNetwork so the live field mapping can be confirmed from
    // the run logs. Safe to leave off in normal operation.
    diagnose: bool(env.DIAGNOSE, false),
    // Incremental mode only pushes products changed since the last successful
    // run (tracked in the state file). The XML feed, when produced, always
    // contains the full catalogue — Google feeds are full snapshots.
    incremental: bool(env.INCREMENTAL, false),
    statePath: env.STATE_PATH || 'output/.sync-state.json',
    // Delete from Google any product that was synced previously but is no
    // longer in DecoNetwork. Opt-in because it is destructive.
    cleanupStale: bool(env.CLEANUP_STALE, false),
    // Safety rail: if a run would delete more than this fraction of the
    // previously-synced catalogue, skip cleanup and warn — this usually means
    // an incomplete DecoNetwork fetch, not a genuine mass removal.
    cleanupMaxFraction: num(env.CLEANUP_MAX_FRACTION, 0.5),
    currency: env.CURRENCY || 'GBP',
    defaultBrand: env.DEFAULT_BRAND || '',
    defaultCondition: env.DEFAULT_CONDITION || 'new',
    feedOutputPath: env.FEED_OUTPUT_PATH || 'output/google-shopping-feed.xml',
    // Markdown run report (empty string disables it).
    reportPath: env.REPORT_PATH ?? 'output/last-run-report.md',
    // Where to source products from: 'deconetwork' (live API) or 'fixture'
    // (bundled sample data — used for demos/tests and as a safe default when
    // no DecoNetwork credentials are present).
    source: (env.PRODUCT_SOURCE || (env.DECONETWORK_API_BASE ? 'deconetwork' : 'fixture')).toLowerCase(),
    fixturePath: env.FIXTURE_PATH || 'fixtures/deconetwork-products.sample.json',
  };

  return config;
}

// Load the DecoNetwork→Google category map and attach it to the config. A
// missing/broken map is non-fatal — the app falls back to the default
// category. Returns the config for convenience.
export async function loadCategoryMap(config) {
  const path = config.google.categoryMapPath;
  if (!path) return config;
  try {
    const { readFile } = await import('node:fs/promises');
    const text = await readFile(path, 'utf8');
    const parsed = JSON.parse(text);
    if (parsed && Array.isArray(parsed.rules)) config.google.categoryMap = parsed;
  } catch {
    // fall back to default category silently — this is an optional enrichment
  }
  return config;
}

// Validate that the config is coherent for the requested run. Returns a list of
// human-readable problems (empty = OK). Callers decide whether problems are
// fatal or should trigger a graceful skip.
export function validateConfig(config) {
  const problems = [];

  if (config.source === 'deconetwork') {
    if (!config.deconetwork.baseUrl) problems.push('DECONETWORK_API_BASE is not set');
    if (!config.deconetwork.username) problems.push('DECONETWORK_USERNAME is not set');
    if (!config.deconetwork.password) problems.push('DECONETWORK_PASSWORD is not set');
  }

  const needsGoogleApi = config.syncMode === 'api' || config.syncMode === 'both';
  if (needsGoogleApi && !config.dryRun) {
    if (!config.google.merchantId) problems.push('GOOGLE_MERCHANT_ID is not set');
    if (!config.google.dataSourceId) problems.push('GOOGLE_DATA_SOURCE_ID is not set');
    if (!config.google.serviceAccountJson && !config.google.serviceAccountFile) {
      problems.push('GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE is not set');
    }
  }

  if (!['api', 'feed', 'both'].includes(config.syncMode)) {
    problems.push(`SYNC_MODE must be one of api|feed|both (got "${config.syncMode}")`);
  }

  return problems;
}
