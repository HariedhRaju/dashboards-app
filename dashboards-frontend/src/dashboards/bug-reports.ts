import type { DashboardDef } from '../types';

/**
 * Bug Bot — Quality Command Center.
 *
 * Row 1 — 4 KPIs
 * Row 2 — velocity (6) + fix-rate gauge (3) + severity donut (3)
 * Row 3 — MTTR by severity bar (6) + aging backlog bar (6)
 * Row 4 — status breakdown table (6) + reporter breakdown table (6)
 * Row 5 — project breakdown (6) + severity×status matrix (6)
 * Row 6 — full telemetry log (12)
 *
 * Breakdown widgets hide when their dimension is already filtered.
 */
const bugReportsDashboard: DashboardDef = {
  slug: 'bug-reports',
  title: 'Bug Bot — Quality Command Center',
  category: 'quality',
  filterBar: [
    { param: 'project_id',  dimension: 'bug_projects',   placeholder: 'All Game Projects' },
    { param: 'issue_no',    dimension: 'bug_issues',     placeholder: 'All Bug Issues (#)' },
    { param: 'severity',    dimension: 'bug_severities', placeholder: 'All Severities' },
    { param: 'status',      dimension: 'bug_statuses',   placeholder: 'All Statuses' },
  ],
  layout: [
    // ── Row 1: KPIs ──
    { w: 3, h: 1, widget: {
      type: 'metric', metric: 'bugs.total',
      title: 'Total Bug Reports', subtitle: 'All reports in range',
      icon: 'activity', iconColor: 'blue', goodDirection: 'neutral',
    }},
    { w: 3, h: 1, widget: {
      type: 'metric', metric: 'bugs.backlog',
      title: 'Unresolved Backlog', subtitle: 'Not yet closed',
      icon: 'layers', iconColor: 'amber', goodDirection: 'down',
    }},
    { w: 3, h: 1, widget: {
      type: 'metric', metric: 'bugs.p1_open',
      title: 'P1 Critical Open', subtitle: 'Highest severity, unresolved',
      icon: 'zap', iconColor: 'orange', goodDirection: 'down',
    }},
    { w: 3, h: 1, widget: {
      type: 'metric', metric: 'bugs.reporters.active',
      title: 'Active QA Reporters', subtitle: 'Distinct reporters in range',
      icon: 'users', iconColor: 'purple', goodDirection: 'neutral',
    }},

    // ── Row 2: velocity + gauge + severity donut ──
    { w: 6, h: 3, widget: {
      type: 'timeseries', metric: 'bugs.velocity',
      title: 'Bug Velocity — Discovery vs Resolution', stacked: false,
    }},
    { w: 3, h: 3, widget: {
      type: 'gauge', metric: 'bugs.fix_rate',
      title: 'Resolution Rate', badge: 'closed / total', unit: 'FIX RATE',
    }},
    { w: 3, h: 3, widget: {
      type: 'donut', metric: 'bugs.by_severity',
      title: 'Severity Breakdown', colorScheme: 'severity',
    }, hideWhen: ['severity'] },

    // ── Row 3: MTTR + aging ──
    { w: 6, h: 3, widget: {
      type: 'bar', metric: 'bugs.mttr_by_severity',
      title: 'Median Time to Resolution by Severity (approx)', colorScheme: 'severity',
    }},
    { w: 6, h: 3, widget: {
      type: 'bar', metric: 'bugs.aging_backlog',
      title: 'Aging Backlog — How Old Are Open Bugs',
    }},

    // ── Row 4: status + reporter tables ──
    { w: 6, h: 4, widget: {
      type: 'table', metric: 'bugs.breakdown.status',
      title: 'Status Workflow Distribution', compact: true,
      columnConfig: {
        status: { label: 'Status', format: 'status-badge' },
        count:  { label: 'Count' },
        pct:    { label: '% of Total', format: 'percent-cell' },
      },
    }, hideWhen: ['status'] },

    { w: 6, h: 4, widget: {
      type: 'table', metric: 'bugs.breakdown.reporter',
      title: 'Top Reporters', compact: true,
      sortableColumns: ['reported', 'closed'],
      columnConfig: {
        reporter:   { label: 'Reporter' },
        email:      { label: 'Email', format: 'muted' },
        reported:   { label: 'Reported' },
        closed:     { label: 'Closed' },
        close_rate: { label: 'Close %', format: 'percent-cell' },
      },
    }, hideWhen: ['reported_by'] },

    // ── Row 5: project + severity×status matrix ──
    { w: 6, h: 4, widget: {
      type: 'table', metric: 'bugs.breakdown.project',
      title: 'Breakdown by Project', compact: true,
      columnConfig: {
        project:    { label: 'Project' },
        code:       { label: 'Code', format: 'badge' },
        total:      { label: 'Total' },
        unresolved: { label: 'Unresolved' },
        p1_open:    { label: 'P1 Open' },
      },
    }, hideWhen: ['project_id'] },

    { w: 6, h: 4, widget: {
      type: 'table', metric: 'bugs.severity_status_matrix',
      title: 'Severity × Status Matrix', compact: true,
      columnConfig: {
        severity:    { label: 'Severity', format: 'severity-badge' },
        open:        { label: 'Open' },
        in_progress: { label: 'In Progress' },
        fixed:       { label: 'Fixed' },
        closed:      { label: 'Closed' },
      },
    }, hideWhen: ['severity'] },

    // ── Row 6: full telemetry log ──
    { w: 12, h: 6, widget: {
      type: 'table', metric: 'bugs.telemetry',
      title: 'Live Bug Telemetry Stream',
      sortableColumns: ['issue_no', 'severity', 'status', 'created_at'],
      pageSize: 20,
      columnConfig: {
        issue_no:      { label: 'Bug #', format: 'badge' },
        title:         { label: 'Title' },
        severity:      { label: 'Severity', format: 'severity-badge' },
        status:        { label: 'Status', format: 'status-badge' },
        project_name:  { label: 'Project' },
        reporter_name: { label: 'Reporter' },
        created_at:    { label: 'Created At', format: 'timestamp' },
        age_days:      { label: 'Age', format: 'age' },
      },
    }},
  ],
};

export default bugReportsDashboard;
