import type { DashboardDef } from '../types';

/**
 * ReportIQ — Executive Project Reporting & Progress Intelligence Dashboard
 *
 * Dual-Mode Architecture:
 * 1. Organization / Portfolio Overview (when All Projects is active, project_id is empty)
 *    - Org KPIs (5 metrics)
 *    - Portfolio Progress Matrix (with click-to-drill-down) + Health Distribution Donut
 *    - Report Activity Timeseries + Project Reporting Compliance Table
 *
 * 2. Project Command Center (when a specific Project is selected, project_id is set)
 *    - Project Command Hero Banner (KPIs, Progress, Risks, Return button)
 *    - Multi-Dimensional Health Breakdown + "What Changed?" Delta Highlights
 *    - Project Journey Timeline
 *    - Planned vs Actual Progress Trend (60 Days) + Attention Required Risk Alerts
 *    - Milestone Roadmap Tracker + Recent DSR/WSR History Table
 */
const reportIqDashboard: DashboardDef = {
  slug: 'report-iq',
  title: 'ReportIQ — Project Reporting & Progress Intelligence',
  category: 'executive',
  filterBar: [
    { param: 'project_id',    dimension: 'projects',         placeholder: 'All projects' },
    { param: 'report_type',   dimension: 'report_types',     placeholder: 'All report types' },
    { param: 'health_status', dimension: 'project_statuses', placeholder: 'All health statuses' },
    { param: 'template_id',   dimension: 'report_templates', placeholder: 'All templates' },
  ],
  layout: [
    // ══════════════════════════════════════════════════════════════════════════
    //  MODE 1: ORGANIZATION / PORTFOLIO INTELLIGENCE (hideWhen: ['project_id'])
    // ══════════════════════════════════════════════════════════════════════════

    // ── Row 1: Org KPIs ──
    {
      w: 3, h: 1, hideWhen: ['project_id'],
      widget: {
        type: 'metric', metric: 'reportiq.kpi.projects_count',
        title: 'Active Portfolio Projects', subtitle: 'Monitored engineering streams',
        icon: 'layers', iconColor: 'blue', goodDirection: 'up',
      },
    },
    {
      w: 2, h: 1, hideWhen: ['project_id'],
      widget: {
        type: 'metric', metric: 'reportiq.kpi.files_processed',
        title: 'Files & Specs Ingested', subtitle: 'Technical documentation',
        icon: 'link', iconColor: 'cyan', goodDirection: 'up',
      },
    },
    {
      w: 2, h: 1, hideWhen: ['project_id'],
      widget: {
        type: 'metric', metric: 'reportiq.kpi.dsr_count',
        title: 'Daily Reports (DSR)', subtitle: 'Automated daily check-ins',
        icon: 'activity', iconColor: 'purple', goodDirection: 'up',
      },
    },
    {
      w: 2, h: 1, hideWhen: ['project_id'],
      widget: {
        type: 'metric', metric: 'reportiq.kpi.wsr_count',
        title: 'Weekly Reports (WSR)', subtitle: 'Executive weekly digests',
        icon: 'zap', iconColor: 'amber', goodDirection: 'up',
      },
    },
    {
      w: 3, h: 1, hideWhen: ['project_id'],
      widget: {
        type: 'metric', metric: 'reportiq.kpi.org_coverage',
        title: 'Reporting Compliance Rate', subtitle: 'On-time report submissions',
        icon: 'cpu', iconColor: 'green', goodDirection: 'up',
      },
    },

    // ── Row 2: Portfolio Progress Matrix + Health Distribution ──
    {
      w: 8, h: 4, hideWhen: ['project_id'],
      widget: {
        type: 'portfolio_matrix', metric: 'reportiq.portfolio.matrix',
        title: 'Project Portfolio Progress & Delivery Matrix',
      },
    },
    {
      w: 4, h: 4, hideWhen: ['project_id'],
      widget: {
        type: 'donut', metric: 'reportiq.health_distribution',
        title: 'Portfolio Project Health Distribution', colorScheme: 'status',
      },
    },

    // ── Row 3: Report Activity Timeseries + Coverage Table ──
    {
      w: 7, h: 3, hideWhen: ['project_id'],
      widget: {
        type: 'timeseries', metric: 'reportiq.activity.timeseries',
        title: 'Report Publishing Velocity & Frequency (DSR vs WSR)',
      },
    },
    {
      w: 5, h: 3, hideWhen: ['project_id'],
      widget: {
        type: 'table', metric: 'reportiq.report_coverage.table',
        title: 'Project Reporting Compliance & Coverage', compact: true,
        columnConfig: {
          project_name:     { label: 'Project' },
          project_code:     { label: 'Code', format: 'badge' },
          coverage_pct:     { label: 'Coverage', format: 'percent-cell' },
          dsr_count:        { label: 'DSR', format: 'number' },
          wsr_count:        { label: 'WSR', format: 'number' },
          actual_reports:   { label: 'Total Filed', format: 'bold-number' },
        },
      },
    },

    // ══════════════════════════════════════════════════════════════════════════
    //  MODE 2: PROJECT COMMAND CENTER (showWhen: ['project_id'])
    // ══════════════════════════════════════════════════════════════════════════

    // ── Row 1: Project Command Hero Banner ──
    {
      w: 12, h: 2, showWhen: ['project_id'],
      widget: {
        type: 'project_banner', metric: 'reportiq.project.summary',
      },
    },

    // ── Row 2: Multi-dim Health Breakdown + What Changed Intelligence ──
    {
      w: 5, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'health_bar', metric: 'reportiq.project.health_breakdown',
        title: 'Multi-Dimensional Engineering Health',
      },
    },
    {
      w: 7, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'what_changed', metric: 'reportiq.project.what_changed',
        title: 'Sprint & Release Delta Intelligence (What Changed?)',
      },
    },

    // ── Row 3: Project Journey Timeline ──
    {
      w: 12, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'timeline', metric: 'reportiq.project.timeline',
        title: 'Project Journey, Sprint Completions & Release Timeline',
      },
    },

    // ── Row 4: Planned vs Actual Progress Trend + Attention Required Risks ──
    {
      w: 7, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'progress_trend', metric: 'reportiq.project.progress_trend',
        title: 'Planned vs Actual Execution Velocity Trend (60 Days)',
      },
    },
    {
      w: 5, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'attention_required', metric: 'reportiq.project.attention_required',
        title: 'Attention Required — Active Risks & Critical Blockers',
      },
    },

    // ── Row 5: Milestone Journey Tracker + DSR/WSR History Table ──
    {
      w: 6, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'milestone_tracker', metric: 'reportiq.project.milestones',
        title: 'Release Gate Milestones Roadmap',
      },
    },
    {
      w: 6, h: 3, showWhen: ['project_id'],
      widget: {
        type: 'table', metric: 'reportiq.project.report_history',
        title: 'Recent Status Reports & Telemetry Filed', compact: true,
        columnConfig: {
          title:         { label: 'Report Title' },
          report_type:   { label: 'Type', format: 'report-type-badge' },
          template_name: { label: 'Template' },
          author_name:   { label: 'Author' },
          output_format: { label: 'Format', format: 'format-badge' },
          status:        { label: 'Stage', format: 'pipeline-stage-badge' },
          created_at:    { label: 'Created At', format: 'timestamp' },
        },
      },
    },
  ],
};

export default reportIqDashboard;
