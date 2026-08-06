import { test } from 'node:test';
import assert from 'node:assert/strict';
import { rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runSync } from '../src/sync.js';
import { saveState } from '../src/state.js';
import { productInputName } from '../src/google.js';
import { loadConfig } from '../src/config.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, '..', 'fixtures', 'deconetwork-products.sample.json');
// Fixture product_ids are 1000..1082.

test('productInputName builds the Merchant API resource name', () => {
  const cfg = loadConfig({ GOOGLE_MERCHANT_ID: '123', GOOGLE_CONTENT_LANGUAGE: 'en', GOOGLE_FEED_LABEL: 'GB' });
  assert.equal(
    productInputName(cfg, 'RX101'),
    'accounts/123/productInputs/en~GB~RX101'
  );
});

test('cleanup deletes ids present before but gone from DecoNetwork', async () => {
  const statePath = join(tmpdir(), `cln-state-${process.pid}.json`);
  // Seed a prior catalogue: three ids still present + one that's gone.
  await saveState(statePath, { activeIds: ['1000', '1001', '1002', '999999'] });
  try {
    const env = {
      PRODUCT_SOURCE: 'fixture',
      FIXTURE_PATH: fixturePath,
      SYNC_MODE: 'api',
      DRY_RUN: 'true', // exercises the diff without touching the network
      CLEANUP_STALE: 'true',
      STATE_PATH: statePath,
      LOG_LEVEL: 'error',
    };
    const s = await runSync({ env, now: '2026-07-24T00:00:00Z' });
    assert.ok(s.cleanup, 'cleanup summary present');
    // Only 999999 is stale; dry-run reports it under skipped.
    assert.equal(s.cleanup.skipped, 1);
  } finally {
    await rm(statePath, { force: true });
  }
});

test('cleanup is skipped when the stale set exceeds the safety threshold', async () => {
  const statePath = join(tmpdir(), `cln-guard-${process.pid}.json`);
  // 3 of 4 prior ids are gone -> 75% > default 50% threshold -> skip.
  await saveState(statePath, { activeIds: ['1000', '777777', '888888', '999999'] });
  try {
    const env = {
      PRODUCT_SOURCE: 'fixture',
      FIXTURE_PATH: fixturePath,
      SYNC_MODE: 'api',
      DRY_RUN: 'true',
      CLEANUP_STALE: 'true',
      STATE_PATH: statePath,
      LOG_LEVEL: 'error',
    };
    const s = await runSync({ env, now: '2026-07-24T00:00:00Z' });
    assert.ok(s.cleanup);
    assert.equal(s.cleanup.skipped, true);
    assert.equal(s.cleanup.reason, 'exceeds-safety-threshold');
    assert.equal(s.cleanup.stale, 3);
  } finally {
    await rm(statePath, { force: true });
  }
});

test('no cleanup on the first run (no prior catalogue)', async () => {
  const statePath = join(tmpdir(), `cln-first-${process.pid}.json`);
  try {
    const env = {
      PRODUCT_SOURCE: 'fixture',
      FIXTURE_PATH: fixturePath,
      SYNC_MODE: 'api',
      DRY_RUN: 'true',
      CLEANUP_STALE: 'true',
      STATE_PATH: statePath,
      LOG_LEVEL: 'error',
    };
    const s = await runSync({ env, now: '2026-07-24T00:00:00Z' });
    assert.equal(s.cleanup, null); // nothing recorded yet -> no cleanup
  } finally {
    await rm(statePath, { force: true });
  }
});
