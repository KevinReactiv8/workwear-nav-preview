import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withRetry, isTransientError } from '../src/retry.js';

test('withRetry returns on first success', async () => {
  let calls = 0;
  const result = await withRetry(async () => {
    calls += 1;
    return 'ok';
  });
  assert.equal(result, 'ok');
  assert.equal(calls, 1);
});

test('withRetry retries then succeeds', async () => {
  let calls = 0;
  const result = await withRetry(
    async () => {
      calls += 1;
      if (calls < 3) {
        const err = new Error('transient');
        err.status = 503;
        throw err;
      }
      return 'recovered';
    },
    { retries: 5, baseDelayMs: 1, maxDelayMs: 2 }
  );
  assert.equal(result, 'recovered');
  assert.equal(calls, 3);
});

test('withRetry gives up after retries exhausted', async () => {
  let calls = 0;
  await assert.rejects(
    withRetry(
      async () => {
        calls += 1;
        const err = new Error('always');
        err.status = 500;
        throw err;
      },
      { retries: 2, baseDelayMs: 1, maxDelayMs: 2 }
    ),
    /always/
  );
  assert.equal(calls, 3); // initial + 2 retries
});

test('withRetry does not retry non-retryable errors', async () => {
  let calls = 0;
  await assert.rejects(
    withRetry(
      async () => {
        calls += 1;
        const err = new Error('bad request');
        err.status = 400;
        throw err;
      },
      { retries: 5, baseDelayMs: 1, shouldRetry: isTransientError }
    ),
    /bad request/
  );
  assert.equal(calls, 1);
});

test('isTransientError classifies correctly', () => {
  assert.equal(isTransientError({ status: 500 }), true);
  assert.equal(isTransientError({ status: 429 }), true);
  assert.equal(isTransientError({ status: 408 }), true);
  assert.equal(isTransientError({ status: 400 }), false);
  assert.equal(isTransientError({ status: 404 }), false);
  assert.equal(isTransientError({ code: 'ECONNRESET' }), true);
  assert.equal(isTransientError({ message: 'socket hang up' }), true);
  assert.equal(isTransientError(null), false);
});
