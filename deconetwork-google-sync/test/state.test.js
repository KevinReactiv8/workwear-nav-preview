import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadState, saveState, changedSince } from '../src/state.js';
import { runSync } from '../src/sync.js';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, '..', 'fixtures', 'deconetwork-products.sample.json');

test('loadState returns {} for a missing file', async () => {
  const state = await loadState(join(tmpdir(), 'does-not-exist-state.json'));
  assert.deepEqual(state, {});
});

test('saveState then loadState round-trips', async () => {
  const path = join(tmpdir(), `state-rt-${process.pid}.json`);
  try {
    await saveState(path, { lastSyncAt: '2026-07-24T00:00:00Z' });
    const state = await loadState(path);
    assert.equal(state.lastSyncAt, '2026-07-24T00:00:00Z');
  } finally {
    await rm(path, { force: true });
  }
});

test('changedSince logic', () => {
  // no cutoff -> always push
  assert.equal(changedSince('2020-01-01', undefined), true);
  // no modified date -> fail safe, push
  assert.equal(changedSince(undefined, '2026-01-01'), true);
  // modified after cutoff -> push
  assert.equal(changedSince('2026-07-24T10:00:00Z', '2026-07-23T00:00:00Z'), true);
  // modified before cutoff -> skip
  assert.equal(changedSince('2026-07-20T10:00:00Z', '2026-07-23T00:00:00Z'), false);
  // unparseable -> push
  assert.equal(changedSince('not-a-date', '2026-07-23T00:00:00Z'), true);
});

test('incremental run writes a watermark and skips unchanged products next run', async () => {
  const statePath = join(tmpdir(), `inc-state-${process.pid}.json`);
  const base = {
    PRODUCT_SOURCE: 'fixture',
    FIXTURE_PATH: fixturePath,
    SYNC_MODE: 'api',
    DRY_RUN: 'false',
    INCREMENTAL: 'true',
    STATE_PATH: statePath,
    // No Google creds, but api-mode push needs them unless dryRun. Use dry?
    // We want a real (non-dry) push path but without network. Force feed mode
    // instead so no Google client is created, yet incremental filtering runs.
    LOG_LEVEL: 'error',
  };
  const feedOut = join(tmpdir(), `inc-feed-${process.pid}.xml`);
  try {
    // Use SYNC_MODE=feed so we exercise incremental filtering + state writing
    // without needing Google credentials. Fixture products have no modified
    // date, so all count as "changed".
    const env1 = { ...base, SYNC_MODE: 'feed', FEED_OUTPUT_PATH: feedOut };
    const s1 = await runSync({ env: env1, now: '2026-07-24T00:00:00Z' });
    assert.equal(s1.incremental, true);
    assert.equal(s1.toPush, s1.valid); // no modified dates -> all pushable
    const state = await loadState(statePath);
    assert.equal(state.lastSyncAt, '2026-07-24T00:00:00Z');
    assert.equal(state.lastRun.advancedWatermark, true);
  } finally {
    await rm(statePath, { force: true });
    await rm(feedOut, { force: true });
  }
});

test('incremental filtering skips products older than the watermark', async () => {
  const statePath = join(tmpdir(), `inc-filter-${process.pid}.json`);
  const feedOut = join(tmpdir(), `inc-filter-feed-${process.pid}.xml`);
  const rawFixture = join(tmpdir(), `inc-filter-src-${process.pid}.json`);
  const { writeFile } = await import('node:fs/promises');
  // Two products: one modified before the watermark, one after.
  await writeFile(
    rawFixture,
    JSON.stringify({
      products: [
        { product_id: 1, name: 'Old', price: 1, url: 'u1', image_url: 'i1', date_modified: '2026-07-01T00:00:00Z' },
        { product_id: 2, name: 'New', price: 2, url: 'u2', image_url: 'i2', date_modified: '2026-07-23T12:00:00Z' },
      ],
    }),
    'utf8'
  );
  await saveState(statePath, { lastSyncAt: '2026-07-20T00:00:00Z' });
  try {
    const env = {
      PRODUCT_SOURCE: 'fixture',
      FIXTURE_PATH: rawFixture,
      SYNC_MODE: 'feed',
      INCREMENTAL: 'true',
      STATE_PATH: statePath,
      FEED_OUTPUT_PATH: feedOut,
      LOG_LEVEL: 'error',
    };
    const s = await runSync({ env, now: '2026-07-24T00:00:00Z' });
    assert.equal(s.valid, 2);
    assert.equal(s.toPush, 1); // only the product modified after the watermark
  } finally {
    await rm(statePath, { force: true });
    await rm(feedOut, { force: true });
    await rm(rawFixture, { force: true });
  }
});
