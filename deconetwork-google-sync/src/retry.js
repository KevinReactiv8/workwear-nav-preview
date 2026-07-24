import { logger } from './logger.js';

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Run an async function, retrying on failure with exponential backoff and
 * jitter. Only retries when `shouldRetry(error)` returns true (default: always).
 *
 * @param {() => Promise<T>} fn
 * @param {object} [opts]
 * @param {number} [opts.retries=4]      number of retries after the first attempt
 * @param {number} [opts.baseDelayMs=1000]
 * @param {number} [opts.maxDelayMs=30000]
 * @param {(err: any) => boolean} [opts.shouldRetry]
 * @param {string} [opts.label]
 * @returns {Promise<T>}
 * @template T
 */
export async function withRetry(fn, opts = {}) {
  const {
    retries = 4,
    baseDelayMs = 1000,
    maxDelayMs = 30000,
    shouldRetry = () => true,
    label = 'operation',
  } = opts;

  let attempt = 0;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      return await fn();
    } catch (err) {
      attempt += 1;
      if (attempt > retries || !shouldRetry(err)) {
        throw err;
      }
      const backoff = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      const jitter = Math.floor(backoff * 0.25 * deterministicJitter(attempt));
      const delay = backoff + jitter;
      logger.warn(`${label} failed, retrying`, {
        attempt,
        retries,
        delayMs: delay,
        error: err?.message || String(err),
      });
      await sleep(delay);
    }
  }
}

// Deterministic pseudo-jitter (0..1) derived from the attempt number so runs are
// reproducible and we avoid Math.random (which is unavailable in some sandboxes).
function deterministicJitter(attempt) {
  const x = Math.sin(attempt * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

// Network / transient HTTP errors worth retrying.
export function isTransientError(err) {
  if (!err) return false;
  const status = err.status || err.code || err?.response?.status;
  if (typeof status === 'number') {
    return status === 408 || status === 429 || (status >= 500 && status <= 599);
  }
  const transientCodes = [
    'ECONNRESET', 'ETIMEDOUT', 'ECONNREFUSED', 'ENOTFOUND',
    'EAI_AGAIN', 'EPIPE', 'ECONNABORTED', 'UND_ERR_CONNECT_TIMEOUT',
  ];
  return transientCodes.includes(err.code) || /network|timeout|socket/i.test(err.message || '');
}
