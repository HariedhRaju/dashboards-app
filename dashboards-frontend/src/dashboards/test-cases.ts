import type { DashboardDef } from '../types';

/**
 * Test Case Generator — Coverage Command Center.
 *
 * Merges three themes on one dashboard:
 *   Operational — runs, volume over time, parse-success, runs log
 *   Coverage    — gaps, feature×priority heatmap, coverage-level mix
 *   Quality     — drift, schema conformance, step depth, test-type, duplication
 *
 * Row 1 — 5 KPIs
 * Row 2 — coverage gaps callout (full width)
 * Row 3 — volume timeseries (6) + parse-success gauge (3) + priority donut (3)
 * Row 4 — feature × priority heatmap (full width)
 * Row 5 — test-type bar (4) + step-depth histogram (4) + duplication table (4)
 * Row 6 — feature breakdown (6) + coverage-level breakdown (6)
 * Row 7 — recent generation runs log (full width)
 * Row 8 — full test-case explorer (full width)
 */
const testCasesDashboard: DashboardDef = {
  slug: 'test-cases',
  title: 'Test Case Generator — Coverage Command Center',
  category: 'quality',
  filterBar: [
    { param: 'project_id',     dimension: 'tc_projects',        placeholder: 'All projects' },
    { param: 'reported_by',    dimension: 'tc_reporters',       placeholder: 'All reporters' },
    { param: 'coverage_level', dimension: 'tc_coverage_levels', placeholder: 'All coverage levels' },
    { param: 'priority',       dimension: 'tc_priorities',      placeholder: 'All priorities' },
    { param: 'test_type',      dimension: 'tc_test_types',      placeholder: 'All test types' },
  ],
  layout: [
    // ── Row 1: KPIs ──
    { w: 3, h: 1, widget: {
      type: 'metric', metric: 'tc.total_cases',
      title: 'Total Test Cases', subtitle: 'Generated in range',
      icon: 'layers', iconColor: 'blue', goodDirection: 'neutral',
    }},
    { w: 2, h: 1, widget: {
      type: 'metric', metric: 'tc.runs',
      title: 'Generation Runs', subtitle: 'GDD uploads',
      icon: 'activity', iconColor: 'cyan', goodDirection: 'neutral',
    }},
    { w: 2, h: 1, widget: {
      type: 'metric', metric: 'tc.features_covered',
      title: 'Features Covered', subtitle: 'With ≥1 case',
      icon: 'zap', iconColor: 'green', goodDirection: 'up',
    }},
    { w: 2, h: 1, widget: {
      type: 'metric', metric: 'tc.drift_count',
      title: 'Priority Drift', subtitle: 'Off-tier cases',
      icon: 'zap', iconColor: 'amber', goodDirection: 'down',
    }},
    { w: 3, h: 1, widget: {
      type: 'metric', metric: 'tc.failed_runs',
      title: 'Failed / Partial Runs', subtitle: 'Needs attention',
      icon: 'zap', iconColor: 'orange', goodDirection: 'down',
    }},

    // ── Row 2: coverage gaps callout ──
    { w: 12, h: 2, widget: {
      type: 'table', metric: 'tc.coverage_gaps',
      title: '⚠ Coverage Gaps — Prioritized Features With Zero Test Cases',
      compact: true,
      columnConfig: {
        feature:  { label: 'Feature' },
        priority: { label: 'Assigned Priority', format: 'priority-pill' },
      },
    }},

    // ── Row 3: volume + gauge + priority donut ──
    { w: 6, h: 3, widget: {
      type: 'timeseries', metric: 'tc.volume_timeseries',
      title: 'Generation Volume Over Time', stacked: false,
    }},
    { w: 3, h: 3, widget: {
      type: 'gauge', metric: 'tc.parse_success_rate',
      title: 'Schema Conformance', badge: 'schema ok', unit: 'PARSE OK',
    }},
    { w: 3, h: 3, widget: {
      type: 'donut', metric: 'tc.by_priority',
      title: 'Priority Mix', colorScheme: 'priority',
    }, hideWhen: ['priority'] },

    // ── Row 4: the heatmap (h:7 fits all ~15 features without scroll) ──
    { w: 12, h: 7, widget: {
      type: 'heatmap', metric: 'tc.feature_priority_matrix',
      title: 'Feature × Priority Coverage Map',
      note: 'red = priority drift from assigned tier',
    }},

    // ── Row 5: quality trio ──
    { w: 4, h: 4, widget: {
      type: 'bar', metric: 'tc.by_test_type',
      title: 'Test Type Distribution (heuristic)',
    }, hideWhen: ['test_type'] },
    { w: 4, h: 4, widget: {
      type: 'bar', metric: 'tc.step_depth_histogram',
      title: 'Step Depth — 0 = parse failure', highlightZero: true,
    }},
    { w: 4, h: 4, widget: {
      type: 'table', metric: 'tc.duplication_clusters',
      title: 'Duplicate Clusters (heuristic)',
      compact: true,
      columnConfig: {
        feature:          { label: 'Feature' },
        normalized_title: { label: 'Normalized Title', format: 'muted' },
        copies:           { label: 'Copies' },
      },
    }},

    // ── Row 6: breakdowns (feature has ~15 rows → h:7) ──
    { w: 6, h: 7, widget: {
      type: 'table', metric: 'tc.breakdown.feature',
      title: 'Breakdown by Feature',
      sortableColumns: ['cases', 'core', 'drift'],
      compact: true,
      columnConfig: {
        feature:      { label: 'Feature' },
        cases:        { label: 'Cases' },
        core:         { label: 'Core' },
        schema_fails: { label: 'Schema Fails' },
        drift:        { label: 'Drift' },
        avg_steps:    { label: 'Avg Steps' },
      },
    }, hideWhen: ['project_id'] },

    { w: 6, h: 7, widget: {
      type: 'table', metric: 'tc.breakdown.coverage',
      title: 'Breakdown by Coverage Level',
      compact: true,
      columnConfig: {
        coverage_level: { label: 'Coverage Level' },
        cases:          { label: 'Cases' },
        features:       { label: 'Features' },
        avg_steps:      { label: 'Avg Steps' },
      },
    }, hideWhen: ['coverage_level'] },

    // ── Row 7: runs log ──
    { w: 12, h: 5, widget: {
      type: 'table', metric: 'tc.runs_log',
      title: 'Recent Generation Runs',
      sortableColumns: ['created_at', 'test_cases_generated', 'duration_ms'],
      pageSize: 15,
      columnConfig: {
        project_name:   { label: 'Project' },
        coverage_level: { label: 'Coverage' },
        status:         { label: 'Status', format: 'status-badge' },
        features:       { label: 'Features' },
        cases:          { label: 'Cases' },
        model:          { label: 'Model', format: 'muted' },
        created_at:     { label: 'Started', format: 'timestamp' },
      },
    }},

    // ── Row 8: case explorer ──
    { w: 12, h: 6, widget: {
      type: 'table', metric: 'tc.case_explorer',
      title: 'Test Case Explorer',
      sortableColumns: ['created_at', 'step_count', 'feature', 'priority'],
      pageSize: 20,
      columnConfig: {
        title:          { label: 'Title' },
        feature:        { label: 'Feature' },
        priority:       { label: 'Priority', format: 'priority-pill' },
        test_type:      { label: 'Type', format: 'test-type' },
        step_count:     { label: 'Steps', format: 'step-count' },
        coverage_level: { label: 'Coverage' },
        drifted:        { label: 'Drift', format: 'drift-dot' },
        schema_ok:      { label: 'OK', format: 'bool-check' },
      },
    }},
  ],
};

export default testCasesDashboard;
