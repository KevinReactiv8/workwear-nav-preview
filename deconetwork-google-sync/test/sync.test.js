import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runSync } from '../src/sync.js';

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, '..', 'fixtures', 'deconetwork-products.sample.json');

test('runSync (fixture + feed) writes a feed and returns a summary', async () => {
  const feedOut = join(tmpdir(), `dn-feed-${process.pid}.xml`);
  const env = {
    PRODUCT_SOURCE: 'fixture',
    FIXTURE_PATH: fixturePath,
    SYNC_MODE: 'feed',
    CURRENCY: 'GBP',
    FEED_OUTPUT_PATH: feedOut,
    LOG_LEVEL: 'error',
  };
  try {
    const summary = await runSync({ env, now: '2026-07-24T00:00:00Z' });
    assert.equal(summary.syncMode, 'feed');
    assert.ok(summary.extracted > 50, 'should extract the fixture products');
    assert.equal(summary.valid, summary.extracted - summary.invalid);
    assert.ok(summary.feed);
    const xml = await readFile(feedOut, 'utf8');
    assert.ok(xml.includes('<rss version="2.0"'));
    // Fixture products carry a numeric product_id (preferred as g:id) and the
    // manufacturer code as g:mpn.
    assert.ok(xml.includes('<g:mpn>RX101</g:mpn>'));
    assert.ok(/<g:id>\d+<\/g:id>/.test(xml));
    assert.ok(xml.includes('<g:price>'));
  } finally {
    await rm(feedOut, { force: true });
  }
});

test('runSync (api + dryRun) does not call the network and reports skipped push', async () => {
  const env = {
    PRODUCT_SOURCE: 'fixture',
    FIXTURE_PATH: fixturePath,
    SYNC_MODE: 'api',
    DRY_RUN: 'true',
    CURRENCY: 'GBP',
    LOG_LEVEL: 'error',
  };
  const summary = await runSync({ env, now: '2026-07-24T00:00:00Z' });
  assert.equal(summary.dryRun, true);
  assert.ok(summary.push);
  assert.equal(summary.push.succeeded, 0);
  assert.equal(summary.push.failed, 0);
  assert.ok(summary.push.skipped > 0);
});

test('runSync skips cleanly when live source is unconfigured (non-strict)', async () => {
  const env = {
    PRODUCT_SOURCE: 'deconetwork', // but no credentials
    SYNC_MODE: 'feed',
    LOG_LEVEL: 'error',
  };
  const summary = await runSync({ env });
  assert.equal(summary.skipped, true);
  assert.equal(summary.reason, 'incomplete-config');
  assert.ok(summary.problems.length > 0);
});

test('runSync throws in STRICT mode when config is invalid', async () => {
  const env = {
    PRODUCT_SOURCE: 'deconetwork',
    SYNC_MODE: 'feed',
    STRICT: 'true',
    LOG_LEVEL: 'error',
  };
  await assert.rejects(runSync({ env }), /Configuration invalid/);
});
