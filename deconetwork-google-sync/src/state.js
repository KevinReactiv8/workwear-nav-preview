import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { logger } from './logger.js';

// Small JSON state file that survives between runs. Used to remember when we
// last synced so incremental runs only push products changed since then.
// A missing or corrupt state file is treated as "no prior run" rather than an
// error — the job must never fail because of its own bookkeeping.

export async function loadState(path) {
  try {
    const text = await readFile(path, 'utf8');
    return JSON.parse(text);
  } catch (err) {
    if (err.code !== 'ENOENT') {
      logger.warn('State file unreadable — treating as first run', {
        path,
        error: err.message,
      });
    }
    return {};
  }
}

export async function saveState(path, state) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, JSON.stringify(state, null, 2) + '\n', 'utf8');
  logger.info('Saved sync state', { path, lastSyncAt: state.lastSyncAt });
}

// Decide whether a product should be pushed this run. In full mode, always.
// In incremental mode, push when we have no prior sync, the product has no
// known modified date (fail safe — push it), or it changed at/after the
// cutoff.
export function changedSince(modifiedAt, cutoffIso) {
  if (!cutoffIso) return true;
  if (!modifiedAt) return true;
  const modified = Date.parse(modifiedAt);
  const cutoff = Date.parse(cutoffIso);
  if (Number.isNaN(modified) || Number.isNaN(cutoff)) return true; // unparseable -> include
  return modified >= cutoff;
}
