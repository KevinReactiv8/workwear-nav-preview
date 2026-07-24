// Minimal structured logger. Emits single-line JSON to stdout so runs are
// greppable in GitHub Actions / cron logs, plus a human-readable prefix.

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

function currentLevel() {
  const configured = (process.env.LOG_LEVEL || 'info').toLowerCase();
  return LEVELS[configured] ?? LEVELS.info;
}

function emit(level, message, extra) {
  if (LEVELS[level] < currentLevel()) return;
  const record = { level, message, ...(extra || {}) };
  const line = `[${level.toUpperCase()}] ${message}` +
    (extra && Object.keys(extra).length ? ` ${JSON.stringify(extra)}` : '');
  // Warnings and errors go to stderr so a non-zero-signal is visible even when
  // stdout is captured separately.
  const stream = level === 'error' || level === 'warn' ? process.stderr : process.stdout;
  stream.write(line + '\n');
  return record;
}

export const logger = {
  debug: (message, extra) => emit('debug', message, extra),
  info: (message, extra) => emit('info', message, extra),
  warn: (message, extra) => emit('warn', message, extra),
  error: (message, extra) => emit('error', message, extra),
};
