import type { DashboardDef } from '../types';

/**
 * QA Insights — the reporting agent's dashboard.
 *
 * Reads the snapshots the agent ingests from a workbook or a Postgres source,
 * and the narrated report it produces from them.
 *
 * The layout is ordered by decision distance. What a release decision actually
 * turns on is at the top; the raw rows a reader drills into to check the
 * agent's arithmetic are at the bottom.
 *
 *   Row 1 — verdict + narrated summary (8) beside the ranked findings (4)
 *   Row 2 — 5 KPIs: blockers, open bugs, execution, pass rate, localization
 *   Row 3 — bug flow over time (7) + severity mix (5)
 *   Row 4 — localization item × locale matrix (full width)
 *   Row 5 — issue type (4) + test outcomes (4) + localization debt (4)
 *   Row 6 — open Major+ bugs (6) + module coverage (6)
 *   Row 7 — items failing across locales (full width)
 *   Row 8 — bug explorer (full width)
 *   Row 9 — ingest history (full width)
 *
 * Every cell declares what it needs via `requires`, checked against
 * /api/qa/capabilities. A source with no localization sheet does not render
 * seven empty locale tiles reporting one absence — those cells disappear and
 * the survivors rebalance to fill the row. The layout above is the maximum,
 * not the guarantee: what you see is what the data supports.
 */
const qaInsightsDashboard: DashboardDef = {
  slug: 'qa-insights',
  title: 'QA Insights — Reporting Agent',
  category: 'quality',
  capabilities: '/api/qa/capabilities',
  // The snapshot is the unit of scope here, so range presets are inert.
  hideDateRange: true,
  console: 'qa',
  filterBar: [
    { param: 'snapshot_id', dimension: 'qa_snapshots',   placeholder: 'Latest snapshot' },
    { param: 'severity',    dimension: 'qa_severities',  placeholder: 'All severities' },
    { param: 'status',      dimension: 'qa_statuses',    placeholder: 'All statuses' },
    { param: 'issue_type',  dimension: 'qa_issue_types', placeholder: 'All issue types' },
    { param: 'module',      dimension: 'qa_modules',     placeholder: 'All modules' },
    { param: 'dimension',   dimension: 'qa_dimensions',  placeholder: 'All locales' },
  ],
  layout: [
    // ── Row 1: what the agent concluded ──
    {
      // autoHeight: this is a full report now, not a blurb — sections and
      // citations make its height data-dependent.
      w: 8, h: 3, autoHeight: true, requires: ['report'],
      widget: {
        type: 'narrative', metric: 'qa.executive_summary',
        title: 'Executive Summary',
        emptyHint: 'Open "Ingest data" above, then Run analysis.',
      },
    },
    {
      w: 4, h: 3, autoHeight: true, requires: ['report'],
      widget: { type: 'findings', metric: 'qa.findings', title: 'Findings', limit: 6 },
    },

    // ── Row 2: the release-decision KPIs ──
    {
      w: 2, h: 1, requires: ['bugs'],
      widget: {
        type: 'metric', metric: 'qa.open_blockers',
        title: 'Open Blockers', subtitle: 'Blocker + Critical',
        icon: 'zap', iconColor: 'orange', goodDirection: 'down',
      },
    },
    {
      w: 2, h: 1, requires: ['bugs'],
      widget: {
        type: 'metric', metric: 'qa.bugs_open',
        title: 'Open Bugs', subtitle: 'Not yet closed',
        icon: 'activity', iconColor: 'amber', goodDirection: 'down',
      },
    },
    {
      w: 3, h: 1, requires: ['test_cases'],
      widget: {
        type: 'metric', metric: 'qa.execution_rate',
        title: 'Test Execution', subtitle: 'Of the planned suite',
        icon: 'layers', iconColor: 'blue', goodDirection: 'up',
      },
    },
    {
      w: 2, h: 1, requires: ['test_cases'],
      widget: {
        type: 'metric', metric: 'qa.pass_rate',
        title: 'Pass Rate', subtitle: 'Of executed cases',
        icon: 'zap', iconColor: 'green', goodDirection: 'up',
      },
    },
    {
      w: 3, h: 1, requires: ['localization'],
      widget: {
        type: 'metric', metric: 'qa.localization_pass_rate',
        title: 'Localization Pass', subtitle: 'Strings passing outright',
        icon: 'users', iconColor: 'cyan', goodDirection: 'up',
      },
    },

    // ── Row 2b: how much to trust the read, and how thoroughly it was tested ──
    {
      // requires: has_data, not bugs/test_cases/localization — this describes
      // the INGEST, not any one domain, so it stays visible even on a source
      // with none of the others (e.g. a bugs-only Postgres read).
      w: 6, h: 1, requires: ['has_data'],
      widget: {
        type: 'metric', metric: 'qa.confidence_score',
        title: 'Confidence Score', subtitle: 'Source columns resolved cleanly',
        icon: 'cpu', iconColor: 'purple', goodDirection: 'up',
      },
    },
    {
      // requires: modules (>1) — one module's coverage is the same number
      // twice, same rule as the module breakdown table below.
      w: 6, h: 1, requires: ['modules'],
      widget: {
        type: 'metric', metric: 'qa.module_coverage',
        title: 'Module Coverage', subtitle: 'Modules with at least one run',
        icon: 'layers', iconColor: 'green', goodDirection: 'up',
      },
    },

    // ── Row 3: bug flow + severity shape ──
    {
      w: 7, h: 3, requires: ['bug_dates'],
      widget: {
        type: 'timeseries', metric: 'qa.bugs_over_time',
        title: 'Bugs Reported Over Time — Open vs Closed', stacked: true,
      },
    },
    {
      w: 5, h: 3, requires: ['bugs'], hideWhen: ['severity'],
      widget: {
        type: 'donut', metric: 'qa.by_severity',
        title: 'Severity Mix', colorScheme: 'severity',
      },
    },

    // ── Row 4: the localization grid ──
    {
      // Fixed height with internal scroll, not autoHeight: 60 rows expanded is
      // ~1900px of grid that pushes everything below it off the first screen.
      w: 12, h: 8, requires: ['localization'],
      widget: {
        type: 'statusmatrix', metric: 'qa.localization_matrix',
        title: 'Localization — Item × Locale',
        note: 'passing rows hidden',
      },
    },

    // ── Row 5: distribution trio ──
    {
      w: 4, h: 4, requires: ['issue_types'], hideWhen: ['issue_type'],
      widget: { type: 'bar', metric: 'qa.by_issue_type', title: 'Bugs by Issue Type' },
    },
    {
      w: 4, h: 4, requires: ['test_cases'],
      widget: { type: 'bar', metric: 'qa.test_status_mix', title: 'Test Case Outcomes' },
    },
    {
      w: 4, h: 4, requires: ['multi_locale'], hideWhen: ['dimension'],
      widget: {
        type: 'bar', metric: 'qa.localization_by_dimension',
        title: 'Localization Debt by Locale',
      },
    },

    // ── Row 6: what to fix, and where coverage is thin ──
    {
      w: 6, h: 5, requires: ['open_major'],
      widget: {
        type: 'table', metric: 'qa.open_blockers_table',
        title: 'Open Major+ Bugs',
        compact: true,
        columnConfig: {
          bug_key:    { label: 'ID' },
          severity:   { label: 'Severity', format: 'severity-badge' },
          status:     { label: 'Status', format: 'status-badge' },
          issue_type: { label: 'Type', format: 'muted' },
          summary:    { label: 'Summary', align: 'left' },
          build:      { label: 'Build', format: 'muted', hideOn: 'compact' },
        },
      },
    },
    {
      w: 6, h: 5, requires: ['modules'], hideWhen: ['module'],
      widget: {
        type: 'table', metric: 'qa.module_breakdown',
        title: 'Coverage by Module',
        sortableColumns: ['cases', 'executed', 'failed', 'never_run'],
        compact: true,
        columnConfig: {
          module:    { label: 'Module', align: 'left' },
          cases:     { label: 'Cases' },
          executed:  { label: 'Run' },
          passed:    { label: 'Pass' },
          failed:    { label: 'Fail' },
          never_run: { label: 'Never Run' },
          exec_rate: { label: 'Exec %', format: 'percent-cell' },
        },
      },
    },

    // ── Row 7: one defect seen many times ──
    {
      w: 12, h: 5, requires: ['multi_locale'],
      widget: {
        type: 'table', metric: 'qa.systemic_items',
        title: 'Items Failing Across Locales — likely one defect, not many',
        sortableColumns: ['not_passing', 'share'],
        compact: true,
        columnConfig: {
          item:        { label: 'Item', align: 'left' },
          section:     { label: 'Section', format: 'muted' },
          dimensions:  { label: 'Locales Checked' },
          not_passing: { label: 'Not Passing' },
          share:       { label: 'Share', format: 'percent-cell' },
        },
      },
    },

    // ── Row 8: the raw rows behind every number above ──
    {
      w: 12, h: 6, requires: ['bugs'],
      widget: {
        type: 'table', metric: 'qa.bug_explorer',
        title: 'Bug Explorer',
        sortableColumns: ['severity', 'created', 'bug_key', 'status'],
        pageSize: 20,
        columnConfig: {
          bug_key:    { label: 'ID' },
          created:    { label: 'Created', format: 'timestamp' },
          severity:   { label: 'Severity', format: 'severity-badge' },
          status:     { label: 'Status', format: 'status-badge' },
          issue_type: { label: 'Type', format: 'muted' },
          summary:    { label: 'Summary', align: 'left' },
          build:      { label: 'Build', format: 'muted' },
          resolution: { label: 'Resolution', format: 'muted' },
        },
      },
    },
    // Ingest history deliberately omitted: the console's ingest panel already
    // shows what was read and the snapshot dropdown lists every run, so a
    // full-width table repeating both was the least-read tile on the page.
  ],
};

export default qaInsightsDashboard;
