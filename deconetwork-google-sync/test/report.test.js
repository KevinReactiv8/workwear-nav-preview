import { test } from 'node:test';
import assert from 'node:assert/strict';
import { renderReport } from '../src/report.js';

test('renderReport summarises a successful run', () => {
  const md = renderReport({
    now: '2026-07-24T00:00:00Z',
    source: 'deconetwork',
    syncMode: 'both',
    incremental: true,
    extracted: 100,
    valid: 98,
    invalid: 2,
    toPush: 12,
    push: { succeeded: 11, failed: 1, failures: [{ id: 'X', error: 'bad price' }] },
    cleanup: { deleted: 3 },
    feed: { path: 'output/feed.xml', items: 98 },
    invalidSamples: [{ id: 'Y', issues: ['missing imageLink'] }],
  });
  assert.match(md, /# DecoNetwork → Google Shopping/);
  assert.match(md, /\| Extracted \| 100 \|/);
  assert.match(md, /\| Pushed OK \| 11 \|/);
  assert.match(md, /\| Deleted \(stale\) \| 3 \|/);
  assert.match(md, /output\/feed\.xml/);
  assert.match(md, /missing imageLink/);
  assert.match(md, /bad price/);
});

test('renderReport handles a skipped run', () => {
  const md = renderReport({
    now: '2026-07-24T00:00:00Z',
    skipped: true,
    reason: 'incomplete-config',
    problems: ['DECONETWORK_API_BASE is not set'],
  });
  assert.match(md, /SKIPPED \(incomplete-config\)/);
  assert.match(md, /DECONETWORK_API_BASE is not set/);
});
