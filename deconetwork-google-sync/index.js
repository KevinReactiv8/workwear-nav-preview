#!/usr/bin/env node
// Entry point: run one DecoNetwork → Google Shopping sync and exit.
// Scheduled to run every 24 hours (see .github/workflows/sync.yml or cron).

import { runSync } from './src/sync.js';
import { logger } from './src/logger.js';

async function main() {
  try {
    const summary = await runSync();
    // Emit a machine-readable final summary line for log scrapers/monitoring.
    process.stdout.write('SYNC_SUMMARY ' + JSON.stringify(summary) + '\n');
    process.exitCode = 0;
  } catch (err) {
    logger.error('Sync failed', { error: err?.message || String(err) });
    if (err?.summary) {
      process.stdout.write('SYNC_SUMMARY ' + JSON.stringify(err.summary) + '\n');
    }
    process.exitCode = 1;
  }
}

main();
