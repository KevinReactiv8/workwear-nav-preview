// Renders a human-readable Markdown run report from a sync summary. Written to
// disk each run (and uploaded as a CI artifact) so the daily job's outcome is
// reviewable at a glance without digging through logs.

export function renderReport(summary) {
  const s = summary || {};
  const lines = [];
  lines.push('# DecoNetwork → Google Shopping — Sync Report');
  lines.push('');
  lines.push(`- **Run at:** ${s.now || '(unknown)'}`);

  if (s.skipped) {
    lines.push(`- **Result:** SKIPPED (${s.reason})`);
    if (Array.isArray(s.problems) && s.problems.length) {
      lines.push('- **Problems:**');
      for (const p of s.problems) lines.push(`  - ${p}`);
    }
    lines.push('');
    return lines.join('\n') + '\n';
  }

  lines.push(`- **Source:** ${s.source} · **Mode:** ${s.syncMode}` +
    (s.dryRun ? ' · DRY RUN' : '') + (s.incremental ? ' · incremental' : ''));
  lines.push('');
  lines.push('## Products');
  lines.push('');
  lines.push('| Metric | Count |');
  lines.push('| --- | ---: |');
  lines.push(`| Extracted | ${s.extracted ?? 0} |`);
  lines.push(`| Valid | ${s.valid ?? 0} |`);
  lines.push(`| Invalid (skipped) | ${s.invalid ?? 0} |`);
  lines.push(`| Selected to push | ${s.toPush ?? 0} |`);
  if (s.push) {
    lines.push(`| Pushed OK | ${s.push.succeeded ?? 0} |`);
    lines.push(`| Push failed | ${s.push.failed ?? 0} |`);
  }
  if (s.cleanup) {
    lines.push(`| Deleted (stale) | ${s.cleanup.deleted ?? 0} |`);
  }
  lines.push('');

  if (s.feed) {
    lines.push(`**Feed:** \`${s.feed.path}\` (${s.feed.items} items)`);
    lines.push('');
  }

  if (Array.isArray(s.invalidSamples) && s.invalidSamples.length) {
    lines.push('## Invalid products (sample)');
    lines.push('');
    for (const inv of s.invalidSamples) {
      lines.push(`- \`${inv.id}\`: ${inv.issues.join(', ')}`);
    }
    lines.push('');
  }

  if (s.push && Array.isArray(s.push.failures) && s.push.failures.length) {
    lines.push('## Push failures (sample)');
    lines.push('');
    for (const f of s.push.failures.slice(0, 10)) {
      lines.push(`- \`${f.id}\`: ${f.error}`);
    }
    lines.push('');
  }

  return lines.join('\n') + '\n';
}
