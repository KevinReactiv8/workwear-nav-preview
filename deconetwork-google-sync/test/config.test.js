import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadConfig, validateConfig } from '../src/config.js';

test('loadConfig applies sensible defaults', () => {
  const c = loadConfig({});
  assert.equal(c.syncMode, 'api');
  assert.equal(c.currency, 'GBP');
  assert.equal(c.google.contentLanguage, 'en');
  assert.equal(c.google.feedLabel, 'GB');
  assert.equal(c.source, 'fixture'); // no DECONETWORK_API_BASE => fixture
  assert.equal(c.deconetwork.pageSize, 100);
});

test('loadConfig caps DecoNetwork page size at 100', () => {
  const c = loadConfig({ DECONETWORK_PAGE_SIZE: '500' });
  assert.equal(c.deconetwork.pageSize, 100);
});

test('loadConfig picks deconetwork source when base url is present', () => {
  const c = loadConfig({ DECONETWORK_API_BASE: 'https://store.deconetwork.com' });
  assert.equal(c.source, 'deconetwork');
  assert.equal(c.deconetwork.baseUrl, 'https://store.deconetwork.com');
});

test('validateConfig flags missing DecoNetwork credentials', () => {
  const c = loadConfig({ PRODUCT_SOURCE: 'deconetwork', SYNC_MODE: 'feed' });
  const problems = validateConfig(c);
  assert.ok(problems.some((p) => p.includes('DECONETWORK_API_BASE')));
  assert.ok(problems.some((p) => p.includes('DECONETWORK_USERNAME')));
  assert.ok(problems.some((p) => p.includes('DECONETWORK_PASSWORD')));
});

test('validateConfig flags missing Google creds for api mode', () => {
  const c = loadConfig({ PRODUCT_SOURCE: 'fixture', SYNC_MODE: 'api' });
  const problems = validateConfig(c);
  assert.ok(problems.some((p) => p.includes('GOOGLE_MERCHANT_ID')));
  assert.ok(problems.some((p) => p.includes('GOOGLE_DATA_SOURCE_ID')));
  assert.ok(problems.some((p) => p.includes('GOOGLE_SERVICE_ACCOUNT')));
});

test('validateConfig passes for fixture + feed with no creds', () => {
  const c = loadConfig({ PRODUCT_SOURCE: 'fixture', SYNC_MODE: 'feed' });
  assert.deepEqual(validateConfig(c), []);
});

test('validateConfig does not require Google creds in dry run', () => {
  const c = loadConfig({ PRODUCT_SOURCE: 'fixture', SYNC_MODE: 'api', DRY_RUN: 'true' });
  assert.deepEqual(validateConfig(c), []);
});

test('validateConfig rejects an unknown sync mode', () => {
  const c = loadConfig({ SYNC_MODE: 'nonsense' });
  const problems = validateConfig(c);
  assert.ok(problems.some((p) => p.includes('SYNC_MODE')));
});
