/**
 * Build a downloadable PDF from the agent's persisted report.
 *
 * Structured to match a QA weekly-progress-report template: numbered sections,
 * a bug severity table + chart, a test execution chart, a top-critical-issues
 * table, a key-insights table, a recommendations section, and a closing notes
 * section. Where the template asks for something we do not track — a tester
 * roster, a hand-written weekly plan, links to an external JIRA board — that
 * field is left out rather than invented; everything drawn here is copied
 * from the same payload the dashboard reads, from GET /api/qa/report.
 *
 * jsPDF is loaded via dynamic import so it costs nothing on dashboards that
 * never use it — Vite code-splits it into its own chunk, fetched only when a
 * user clicks Download.
 */

// ══════════════════════════════════════════════════════════════════════════
//  Shape of the /api/qa/report payload actually used here
// ══════════════════════════════════════════════════════════════════════════

interface ReportSection { title: string; body: string; citations: string[] }
interface ExecutiveSummary {
  headline: string; narrative: string; sections: ReportSection[];
  risks: string[]; recommendation: string;
}
interface Finding {
  id: string; kind: string; level: 'critical' | 'warning' | 'info'; title: string; detail: string;
}
interface BugStats {
  total: number; open: number; open_blockers: number; open_major_plus: number;
  builds: number; first_reported: string | null; last_reported: string | null;
  by_severity: Record<string, number>; by_build: Record<string, number>;
}
interface TestCaseStats {
  total: number; executed: number; never_run: number;
  execution_rate: number; pass_rate_of_executed: number;
  module_coverage: number; modules_total: number; modules_covered: number;
  by_status: Record<string, number>;
}
interface ConfidenceStats {
  ingest_confidence: number; columns_resolved: number; columns_total: number; warning_count: number;
}
interface LocalizationStats {
  cells: number; dimensions: number; pass_rate: number;
}
interface IngestStats {
  source_label: string; source_kind: string; columns_unresolved: number; warning_count: number;
}
interface EvidenceBug {
  bug_key: string; severity: string; status: string; summary: string;
}
interface EvidenceCase {
  case_ref: string; module: string; priority: string | null; description: string; status: string;
}
interface QaReport {
  snapshot_id: string;
  verdict: 'healthy' | 'caution' | 'at_risk' | 'blocked' | 'unknown';
  generated_at: string;
  model_enabled: boolean;
  model_name: string | null;
  partial: boolean;
  executive_summary: ExecutiveSummary;
  findings: Finding[];
  counts: { critical: number; warning: number; info: number };
  stats: {
    bugs: BugStats; test_cases: TestCaseStats; localization: LocalizationStats; ingest: IngestStats;
    confidence: ConfidenceStats;
  };
  evidence: {
    open_blockers: EvidenceBug[]; open_major: EvidenceBug[];
    never_run_cases: EvidenceCase[]; failed_cases: EvidenceCase[];
  };
}

// ══════════════════════════════════════════════════════════════════════════
//  Palette
// ══════════════════════════════════════════════════════════════════════════

type RGB = [number, number, number];

const VERDICT_COLOR: Record<string, RGB> = {
  healthy: [52, 211, 153], caution: [251, 191, 36],
  at_risk: [251, 146, 60], blocked: [248, 113, 113], unknown: [163, 163, 163],
};
const VERDICT_LABEL: Record<string, string> = {
  healthy: 'HEALTHY', caution: 'CAUTION', at_risk: 'AT RISK',
  blocked: 'BLOCKED', unknown: 'NOT ANALYZED',
};
const SEVERITY_COLOR: Record<string, RGB> = {
  Blocker: [220, 38, 38], Critical: [234, 88, 12], Major: [217, 119, 6],
  Minor: [79, 70, 229], Trivial: [115, 115, 115],
};
const STATUS_COLOR: Record<string, RGB> = {
  Pass: [22, 163, 74], Fail: [220, 38, 38], 'Some Issue': [217, 119, 6],
  Blocked: [219, 39, 119], 'In Progress': [8, 145, 178], 'Not Run': [115, 115, 115],
  Unknown: [115, 115, 115],
};
const LEVEL_COLOR: Record<string, RGB> = {
  critical: [220, 38, 38], warning: [217, 119, 6], info: [107, 114, 128],
};
const LEVEL_IMPACT: Record<string, string> = {
  critical: 'High — release blocking', warning: 'Medium — needs attention', info: 'Low — for awareness',
};
const CHART_FALLBACK: RGB[] = [
  [79, 70, 229], [8, 145, 178], [22, 163, 74], [217, 119, 6], [219, 39, 119], [107, 114, 128],
];

const HEADING_BLUE: RGB = [29, 78, 216];
const TABLE_HEAD_BG: RGB = [219, 234, 254];
const TABLE_HEAD_TEXT: RGB = [30, 58, 138];
const INK: RGB = [23, 23, 23];
const BODY: RGB = [51, 51, 51];
const MUTED: RGB = [107, 107, 107];
const RULE: RGB = [203, 213, 225];

// ══════════════════════════════════════════════════════════════════════════
//  Layout constants
// ══════════════════════════════════════════════════════════════════════════

const PAGE_W = 210;
const PAGE_H = 297;
const MARGIN = 16;
const CONTENT_W = PAGE_W - MARGIN * 2;
const FOOTER_Y = PAGE_H - 10;

// ══════════════════════════════════════════════════════════════════════════
//  Fetch
// ══════════════════════════════════════════════════════════════════════════

async function fetchReport(apiBase: string, snapshotId?: string): Promise<QaReport> {
  const qs = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : '';
  const res = await fetch(`${apiBase}/api/qa/report${qs}`, { credentials: 'include' });
  if (res.status === 404) throw new Error('No analysis has been run for this snapshot yet.');
  if (!res.ok) throw new Error(`Could not load the report (${res.status}).`);
  return res.json();
}

// ══════════════════════════════════════════════════════════════════════════
//  Entry point
// ══════════════════════════════════════════════════════════════════════════

export async function downloadQaReportPdf(apiBase: string, snapshotId?: string): Promise<void> {
  const report = await fetchReport(apiBase, snapshotId);
  const { jsPDF } = await import('jspdf');
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const cursor = { y: MARGIN };

  drawHeader(doc, report, cursor);
  drawVerdictAndHeadline(doc, report, cursor);
  drawExecutiveSummary(doc, report, cursor);
  drawKpiRow(doc, report, cursor);

  heading(doc, cursor, '1. Summary Dashboard');
  drawCoverageBullets(doc, report, cursor);

  subheading(doc, cursor, '1.A Bug Reports Overview');
  drawBugSeverityBlock(doc, report, cursor);
  drawBuildBreakdown(doc, report, cursor);

  subheading(doc, cursor, '1.B Test Plan Execution Overview');
  drawTestExecutionBlock(doc, report, cursor);
  drawEvidenceTable(
    doc, cursor, 'Test Cases Needing Attention',
    ['Case', 'Module', 'Priority', 'Status', 'Description'],
    [...report.evidence.never_run_cases, ...report.evidence.failed_cases]
      .slice(0, 8)
      .map(c => [c.case_ref, c.module, c.priority ?? '—', c.status, c.description]),
    [30, 26, 16, 16, 0],
  );

  heading(doc, cursor, '2. Bug Reporting — Top Critical Issues');
  drawEvidenceTable(
    doc, cursor, '',
    ['Bug ID', 'Summary'],
    (report.evidence.open_blockers.length ? report.evidence.open_blockers : report.evidence.open_major)
      .slice(0, 8)
      .map(b => [b.bug_key, b.summary]),
    [20, 0],
  );

  heading(doc, cursor, '3. Key Insights & Risk Areas');
  drawInsightsTable(doc, report, cursor);

  heading(doc, cursor, '4. Recommendations & Next Steps');
  drawRecommendation(doc, report, cursor);
  drawRiskBullets(doc, report, cursor);

  heading(doc, cursor, '5. Report Notes');
  drawReportNotes(doc, report, cursor);

  stampFooters(doc, report);

  const stamp = report.generated_at.slice(0, 10);
  const label = report.stats.ingest.source_label.replace(/\.[a-z0-9]+$/i, '').replace(/[^\w-]+/g, '_');
  doc.save(`qa-report-${label}-${stamp}.pdf`);
}

// ══════════════════════════════════════════════════════════════════════════
//  Drawing primitives
// ══════════════════════════════════════════════════════════════════════════

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Doc = any;
type Cursor = { y: number };

function setColor(doc: Doc, method: 'setTextColor' | 'setFillColor' | 'setDrawColor', c: RGB) {
  doc[method](c[0], c[1], c[2]);
}

function ensureSpace(doc: Doc, cursor: Cursor, needed: number) {
  if (cursor.y + needed > PAGE_H - 20) {
    doc.addPage();
    cursor.y = MARGIN;
  }
}

function heading(doc: Doc, cursor: Cursor, text: string) {
  ensureSpace(doc, cursor, 13);
  cursor.y += 2;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  setColor(doc, 'setTextColor', HEADING_BLUE);
  doc.text(text, MARGIN, cursor.y);
  cursor.y += 2;
  setColor(doc, 'setDrawColor', HEADING_BLUE);
  doc.setLineWidth(0.5);
  doc.line(MARGIN, cursor.y, PAGE_W - MARGIN, cursor.y);
  cursor.y += 6;
}

function subheading(doc: Doc, cursor: Cursor, text: string) {
  ensureSpace(doc, cursor, 10);
  cursor.y += 1;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(10);
  setColor(doc, 'setTextColor', [30, 41, 59]);
  doc.text(text, MARGIN, cursor.y);
  cursor.y += 5.5;
}

function paragraph(
  doc: Doc, cursor: Cursor, text: string,
  opts: { size?: number; color?: RGB; bold?: boolean; width?: number; x?: number } = {},
) {
  const { size = 9.5, color = BODY, bold = false, width = CONTENT_W, x = MARGIN } = opts;
  doc.setFont('helvetica', bold ? 'bold' : 'normal');
  doc.setFontSize(size);
  setColor(doc, 'setTextColor', color);
  const lines: string[] = doc.splitTextToSize(text, width);
  const lineH = size * 0.42;
  for (const line of lines) {
    ensureSpace(doc, cursor, lineH + 1);
    doc.text(line, x, cursor.y);
    cursor.y += lineH;
  }
  cursor.y += 1.5;
}

function pill(doc: Doc, x: number, y: number, text: string, color: RGB) {
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(8.5);
  const w = doc.getTextWidth(text) + 6;
  setColor(doc, 'setFillColor', color);
  doc.roundedRect(x, y - 4.2, w, 5.6, 1.4, 1.4, 'F');
  doc.setTextColor(255, 255, 255);
  doc.text(text, x + 3, y);
  return w;
}

/** A "•  label" bullet line, wrapping and paginating like a normal paragraph. */
function bullet(doc: Doc, cursor: Cursor, text: string, opts: { color?: RGB } = {}) {
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9.5);
  setColor(doc, 'setTextColor', opts.color ?? BODY);
  const lines: string[] = doc.splitTextToSize(text, CONTENT_W - 6);
  lines.forEach((line, i) => {
    ensureSpace(doc, cursor, 5);
    doc.text(i === 0 ? `•  ${line}` : `   ${line}`, MARGIN, cursor.y);
    cursor.y += 4.6;
  });
}

// ══════════════════════════════════════════════════════════════════════════
//  Header / verdict / executive summary
// ══════════════════════════════════════════════════════════════════════════

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}

function drawHeader(doc: Doc, report: QaReport, cursor: Cursor) {
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(19);
  setColor(doc, 'setTextColor', INK);
  doc.text('QA Progress Report', MARGIN, cursor.y + 3);
  cursor.y += 10;

  setColor(doc, 'setDrawColor', RULE);
  doc.setLineWidth(0.4);
  doc.line(MARGIN, cursor.y, PAGE_W - MARGIN, cursor.y);
  cursor.y += 6;

  // A compact key/value strip — the same information the template's header
  // block carries (project, reporting period, report date). Fields the
  // template asks for that we have no source for — a client name, an FQA/CQA
  // roster — are left out rather than printed blank or invented.
  const b = report.stats.bugs;
  const fields: [string, string][] = [
    ['Project', report.stats.ingest.source_label],
    ['Source', report.stats.ingest.source_kind === 'xlsx' ? 'Workbook upload' : 'Database'],
  ];
  if (b.first_reported && b.last_reported) {
    fields.push(['Reporting Period', `${fmtDate(b.first_reported)} – ${fmtDate(b.last_reported)}`]);
  }
  fields.push(['Report Date', fmtDate(report.generated_at)]);

  doc.setFontSize(9.5);
  for (const [label, value] of fields) {
    ensureSpace(doc, cursor, 5.5);
    doc.setFont('helvetica', 'bold');
    setColor(doc, 'setTextColor', [51, 51, 51]);
    doc.text(`${label}:`, MARGIN, cursor.y);
    doc.setFont('helvetica', 'normal');
    setColor(doc, 'setTextColor', BODY);
    doc.text(value, MARGIN + 34, cursor.y);
    cursor.y += 5.2;
  }
  cursor.y += 3;
}

function drawVerdictAndHeadline(doc: Doc, report: QaReport, cursor: Cursor) {
  const color = VERDICT_COLOR[report.verdict] ?? VERDICT_COLOR.unknown;
  pill(doc, MARGIN, cursor.y, VERDICT_LABEL[report.verdict] ?? 'UNKNOWN', color);
  cursor.y += 7;
  paragraph(doc, cursor, report.executive_summary.headline, { size: 12.5, bold: true, color: INK });
  cursor.y += 1;
}

function drawExecutiveSummary(doc: Doc, report: QaReport, cursor: Cursor) {
  paragraph(doc, cursor, report.executive_summary.narrative, { color: BODY });

  // The LLM's per-theme detail folded in here rather than as its own numbered
  // section — it covers the same ground as "Key Insights" (Section 3) below
  // in more words, and printing both in full would say everything twice.
  for (const section of report.executive_summary.sections) {
    ensureSpace(doc, cursor, 9);
    paragraph(doc, cursor, section.title, { bold: true, size: 9, color: [51, 51, 51] });
    paragraph(doc, cursor, section.body, { size: 8.8, color: BODY });
  }

  const provenance = !report.model_enabled
    ? 'Computed — no model was configured for this analysis.'
    : report.partial
      ? `Partial — ${report.model_name ?? 'the model'} fell back to a computed summary for part of this report.`
      : `Narrated by ${report.model_name ?? 'a language model'}.`;
  paragraph(doc, cursor, provenance, { size: 7.5, color: MUTED });
  cursor.y += 1;
}

// ══════════════════════════════════════════════════════════════════════════
//  KPIs
// ══════════════════════════════════════════════════════════════════════════

interface Kpi { label: string; value: string }

function collectKpis(report: QaReport): Kpi[] {
  const kpis: Kpi[] = [];
  const b = report.stats.bugs, t = report.stats.test_cases, l = report.stats.localization;

  if (b.total > 0) {
    kpis.push({ label: 'Open Blockers', value: String(b.open_blockers) });
    kpis.push({ label: 'Open Bugs', value: String(b.open) });
  }
  if (t.total > 0) {
    kpis.push({ label: 'Test Execution', value: `${(t.execution_rate * 100).toFixed(1)}%` });
    kpis.push({ label: 'Pass Rate', value: `${(t.pass_rate_of_executed * 100).toFixed(1)}%` });
  }
  if (l.cells > 0) {
    kpis.push({ label: 'Localization Pass', value: `${(l.pass_rate * 100).toFixed(1)}%` });
  }
  // A report always implies a snapshot was ingested, so confidence is
  // meaningful unconditionally — unlike the domain KPIs above, it isn't
  // gated on bugs/test_cases/localization existing at all.
  kpis.push({
    label: 'Confidence Score',
    value: `${(report.stats.confidence.ingest_confidence * 100).toFixed(1)}%`,
  });
  // One module's coverage is the same number twice — only worth a KPI when
  // there is an actual spread of modules to be covered or not.
  if (t.modules_total > 1) {
    kpis.push({ label: 'Module Coverage', value: `${(t.module_coverage * 100).toFixed(1)}%` });
  }
  return kpis;
}

// More than this many boxes across CONTENT_W starts wrapping labels like
// "Confidence Score" onto a second line, which crowds the value beneath it —
// wrap to a new KPI row instead of shrinking boxes to fit.
const MAX_KPIS_PER_ROW = 5;

function drawKpiRow(doc: Doc, report: QaReport, cursor: Cursor) {
  const kpis = collectKpis(report);
  if (kpis.length === 0) return;

  const gap = 4;
  const h = 17;

  for (let start = 0; start < kpis.length; start += MAX_KPIS_PER_ROW) {
    const row = kpis.slice(start, start + MAX_KPIS_PER_ROW);
    ensureSpace(doc, cursor, h + 5);
    const w = (CONTENT_W - gap * (row.length - 1)) / row.length;

    row.forEach((kpi, i) => {
      const x = MARGIN + i * (w + gap);
      doc.setDrawColor(219, 234, 254);
      doc.setFillColor(239, 246, 255);
      doc.roundedRect(x, cursor.y, w, h, 1.5, 1.5, 'FD');

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(6.8);
      setColor(doc, 'setTextColor', [71, 85, 105]);
      doc.text(kpi.label.toUpperCase(), x + 3, cursor.y + 5.5, { maxWidth: w - 6 });

      doc.setFont('helvetica', 'bold');
      doc.setFontSize(12.5);
      setColor(doc, 'setTextColor', HEADING_BLUE);
      doc.text(kpi.value, x + 3, cursor.y + 13.5);
    });

    cursor.y += h + 4;
  }
  cursor.y += 3;
}

// ══════════════════════════════════════════════════════════════════════════
//  1. Summary Dashboard — coverage bullets
// ══════════════════════════════════════════════════════════════════════════

/**
 * What the template calls "Resource Allocation" is a tester headcount — this
 * agent has no source for staffing, so rather than print a fabricated roster
 * this uses the same "at a glance" bullet pattern for what the agent DOES
 * know: how much of the source this report actually covers.
 */
function drawCoverageBullets(doc: Doc, report: QaReport, cursor: Cursor) {
  const b = report.stats.bugs, t = report.stats.test_cases, l = report.stats.localization;
  const lines: string[] = [];
  if (b.total > 0) lines.push(`${b.total} bugs tracked across ${b.builds || 1} build(s)`);
  if (t.total > 0) lines.push(`${t.total} test cases planned`);
  if (l.cells > 0) lines.push(`${l.cells} localization strings checked across ${l.dimensions} locale(s)`);
  if (lines.length === 0) return;

  for (const line of lines) bullet(doc, cursor, line);
  cursor.y += 2;
}

// ══════════════════════════════════════════════════════════════════════════
//  Charts
// ══════════════════════════════════════════════════════════════════════════

/** The smallest "nice" round number ≥ v, so gridlines land on 5/10/20/50/… */
function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / mag;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * mag;
}

/**
 * A small vertical bar chart: gridlines, value labels above each bar, and a
 * category label below. Sized to sit comfortably under a subheading without
 * dominating the page — this is a supporting chart, not the report's focus.
 */
function drawBarChart(
  doc: Doc, cursor: Cursor,
  entries: [string, number][], colorFor: (key: string, i: number) => RGB,
) {
  if (entries.length === 0) return;
  const chartH = 30;
  ensureSpace(doc, cursor, chartH + 12);

  const top = cursor.y;
  const max = niceCeil(Math.max(...entries.map(([, v]) => v)));
  const gridlines = [0, 0.5, 1];

  setColor(doc, 'setDrawColor', RULE);
  doc.setLineWidth(0.2);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(6.5);
  for (const g of gridlines) {
    const y = top + chartH - g * chartH;
    doc.line(MARGIN, y, PAGE_W - MARGIN, y);
    setColor(doc, 'setTextColor', MUTED);
    doc.text(String(Math.round(max * g)), MARGIN, y - 0.8);
  }

  const gap = 3;
  const barW = Math.min(16, (CONTENT_W - gap * (entries.length - 1)) / entries.length);
  const totalW = barW * entries.length + gap * (entries.length - 1);
  const startX = MARGIN + (CONTENT_W - totalW) / 2;

  entries.forEach(([key, value], i) => {
    const x = startX + i * (barW + gap);
    const barH = max > 0 ? (value / max) * chartH : 0;
    setColor(doc, 'setFillColor', colorFor(key, i));
    doc.rect(x, top + chartH - barH, barW, Math.max(barH, 0.3), 'F');

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(7);
    setColor(doc, 'setTextColor', INK);
    doc.text(String(value), x + barW / 2, top + chartH - barH - 1.2, { align: 'center' });

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(6.5);
    setColor(doc, 'setTextColor', [51, 51, 51]);
    const label = key.length > 10 ? `${key.slice(0, 9)}…` : key;
    doc.text(label, x + barW / 2, top + chartH + 4, { align: 'center', maxWidth: barW + gap });
  });

  cursor.y = top + chartH + 9;
}

function drawBugSeverityBlock(doc: Doc, report: QaReport, cursor: Cursor) {
  const b = report.stats.bugs;
  if (b.total === 0) return;

  paragraph(doc, cursor, `Total Bugs Reported: ${b.total}`, { bold: true, size: 9.5, color: INK });

  const entries = Object.entries(b.by_severity).filter(([, v]) => v > 0) as [string, number][];

  // A compact Severity | Count table — same shape as the template's own.
  ensureSpace(doc, cursor, 6 + entries.length * 5.5);
  simpleTable(doc, cursor, ['Severity', 'Count'], entries.map(([k, v]) => [k, String(v)]), [CONTENT_W - 30, 30]);
  cursor.y += 2;

  drawBarChart(doc, cursor, entries, (k, i) => SEVERITY_COLOR[k] ?? CHART_FALLBACK[i % CHART_FALLBACK.length]);
}

function drawBuildBreakdown(doc: Doc, report: QaReport, cursor: Cursor) {
  const builds = Object.entries(report.stats.bugs.by_build) as [string, number][];
  // One build is the same number twice — only worth a table when there is an
  // actual comparison to show.
  if (builds.length < 2) return;

  paragraph(doc, cursor, 'Bugs by Build', { bold: true, size: 9, color: [51, 51, 51] });
  ensureSpace(doc, cursor, 6 + builds.length * 5.5);
  simpleTable(doc, cursor, ['Build', 'Bugs'], builds.map(([k, v]) => [k, String(v)]), [CONTENT_W - 30, 30]);
  cursor.y += 2;
}

function drawTestExecutionBlock(doc: Doc, report: QaReport, cursor: Cursor) {
  const t = report.stats.test_cases;
  if (t.total === 0) return;

  paragraph(
    doc, cursor,
    `Execution Progress: ${(t.execution_rate * 100).toFixed(1)}% executed ` +
    `(${t.executed} of ${t.total} planned cases)`,
    { bold: true, size: 9.5, color: INK },
  );

  const entries = Object.entries(t.by_status).filter(([, v]) => v > 0) as [string, number][];
  drawBarChart(doc, cursor, entries, (k, i) => STATUS_COLOR[k] ?? CHART_FALLBACK[i % CHART_FALLBACK.length]);
}

// ══════════════════════════════════════════════════════════════════════════
//  Tables
// ══════════════════════════════════════════════════════════════════════════

/** A compact table with no title of its own — used inline under a paragraph. */
function simpleTable(doc: Doc, cursor: Cursor, columns: string[], rows: string[][], widths: number[]) {
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7.5);
  setColor(doc, 'setFillColor', TABLE_HEAD_BG);
  doc.rect(MARGIN, cursor.y - 4, CONTENT_W, 6, 'F');
  setColor(doc, 'setTextColor', TABLE_HEAD_TEXT);
  let cx = MARGIN + 2;
  columns.forEach((col, i) => { doc.text(col.toUpperCase(), cx, cursor.y); cx += widths[i]; });
  cursor.y += 4;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  rows.forEach((row, ri) => {
    ensureSpace(doc, cursor, 6);
    if (ri % 2 === 1) {
      setColor(doc, 'setFillColor', [248, 250, 252]);
      doc.rect(MARGIN, cursor.y - 3.5, CONTENT_W, 5.5, 'F');
    }
    cx = MARGIN + 2;
    setColor(doc, 'setTextColor', INK);
    row.forEach((cell, ci) => { doc.text(cell, cx, cursor.y); cx += widths[ci]; });
    cursor.y += 5.5;
  });
}

/** A titled table whose rows may need wrapping/truncation to fit a column. */
function drawEvidenceTable(
  doc: Doc, cursor: Cursor, title: string, columns: string[], rows: string[][], widths: number[],
) {
  if (rows.length === 0) return;
  const fixed = widths.reduce((s, w) => s + w, 0);
  const resolved = widths.map(w => (w === 0 ? CONTENT_W - fixed : w));

  if (title) subheading(doc, cursor, title);
  ensureSpace(doc, cursor, 8);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7.5);
  setColor(doc, 'setFillColor', TABLE_HEAD_BG);
  doc.rect(MARGIN, cursor.y - 4, CONTENT_W, 6, 'F');
  setColor(doc, 'setTextColor', TABLE_HEAD_TEXT);
  let cx = MARGIN + 2;
  columns.forEach((col, i) => { doc.text(col.toUpperCase(), cx, cursor.y); cx += resolved[i]; });
  cursor.y += 4;

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  rows.forEach((row, ri) => {
    ensureSpace(doc, cursor, 8);
    if (ri % 2 === 1) {
      setColor(doc, 'setFillColor', [248, 250, 252]);
      doc.rect(MARGIN, cursor.y - 3.5, CONTENT_W, 6.5, 'F');
    }
    cx = MARGIN + 2;
    setColor(doc, 'setTextColor', INK);
    row.forEach((cell, ci) => {
      const clipped = doc.splitTextToSize(cell, resolved[ci] - 2)[0] ?? '';
      doc.text(clipped, cx, cursor.y);
      cx += resolved[ci];
    });
    cursor.y += 6;
  });
  cursor.y += 3;
}

/** Area | Insight/Risk Description | Impact — the template's own three columns. */
function drawInsightsTable(doc: Doc, report: QaReport, cursor: Cursor) {
  if (report.findings.length === 0) {
    paragraph(doc, cursor, 'No findings were raised for this snapshot.', { color: MUTED });
    return;
  }
  const widths = [34, CONTENT_W - 34 - 34, 34];
  ensureSpace(doc, cursor, 8);

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7.5);
  setColor(doc, 'setFillColor', TABLE_HEAD_BG);
  doc.rect(MARGIN, cursor.y - 4, CONTENT_W, 6, 'F');
  setColor(doc, 'setTextColor', TABLE_HEAD_TEXT);
  let cx = MARGIN + 2;
  ['Area', 'Insight / Risk Description', 'Impact'].forEach((col, i) => {
    doc.text(col.toUpperCase(), cx, cursor.y); cx += widths[i];
  });
  cursor.y += 4;

  doc.setFontSize(8);
  report.findings.slice(0, 8).forEach((f, ri) => {
    const area = f.kind.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    const bodyLines: string[] = doc.splitTextToSize(f.detail, widths[1] - 3);
    const rowH = Math.max(bodyLines.length * 4, 6) + 1.5;
    ensureSpace(doc, cursor, rowH);

    if (ri % 2 === 1) {
      setColor(doc, 'setFillColor', [248, 250, 252]);
      doc.rect(MARGIN, cursor.y - 3.5, CONTENT_W, rowH, 'F');
    }
    cx = MARGIN + 2;
    doc.setFont('helvetica', 'bold');
    setColor(doc, 'setTextColor', INK);
    doc.text(area, cx, cursor.y, { maxWidth: widths[0] - 3 });
    cx += widths[0];

    doc.setFont('helvetica', 'normal');
    setColor(doc, 'setTextColor', BODY);
    doc.text(bodyLines, cx, cursor.y);
    cx += widths[1];

    setColor(doc, 'setFillColor', LEVEL_COLOR[f.level] ?? LEVEL_COLOR.info);
    doc.circle(cx + 1.2, cursor.y - 1.2, 1.2, 'F');
    doc.setFont('helvetica', 'normal');
    setColor(doc, 'setTextColor', BODY);
    const impact = LEVEL_IMPACT[f.level] ?? f.level;
    const impactLines: string[] = doc.splitTextToSize(impact, widths[2] - 5);
    doc.text(impactLines, cx + 4, cursor.y);

    cursor.y += rowH;
  });
  cursor.y += 2;
}

// ══════════════════════════════════════════════════════════════════════════
//  4. Recommendations & Next Steps
// ══════════════════════════════════════════════════════════════════════════

function drawRecommendation(doc: Doc, report: QaReport, cursor: Cursor) {
  const { recommendation } = report.executive_summary;
  if (!recommendation) return;

  ensureSpace(doc, cursor, 16);
  setColor(doc, 'setFillColor', [239, 246, 255]);
  setColor(doc, 'setDrawColor', [191, 219, 254]);
  const lines: string[] = doc.splitTextToSize(recommendation, CONTENT_W - 8);
  const boxH = lines.length * 4.2 + 8;
  doc.roundedRect(MARGIN, cursor.y, CONTENT_W, boxH, 1.5, 1.5, 'FD');
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(7.5);
  setColor(doc, 'setTextColor', HEADING_BLUE);
  doc.text('RECOMMENDATION', MARGIN + 4, cursor.y + 5);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(9);
  setColor(doc, 'setTextColor', [30, 58, 138]);
  doc.text(lines, MARGIN + 4, cursor.y + 10);
  cursor.y += boxH + 5;
}

function drawRiskBullets(doc: Doc, report: QaReport, cursor: Cursor) {
  const { risks } = report.executive_summary;
  if (risks.length === 0) return;
  paragraph(doc, cursor, 'Items to address before the next review:', { bold: true, size: 9, color: [51, 51, 51] });
  for (const risk of risks) bullet(doc, cursor, risk);
}

// ══════════════════════════════════════════════════════════════════════════
//  5. Report Notes
// ══════════════════════════════════════════════════════════════════════════

function drawReportNotes(doc: Doc, report: QaReport, cursor: Cursor) {
  const { columns_unresolved, warning_count } = report.stats.ingest;
  const { ingest_confidence, columns_resolved, columns_total } = report.stats.confidence;
  bullet(doc, cursor, `Snapshot: ${report.snapshot_id}`, { color: MUTED });
  bullet(doc, cursor, `Generated ${new Date(report.generated_at).toLocaleString()}`, { color: MUTED });
  bullet(
    doc, cursor,
    `Confidence Score: ${(ingest_confidence * 100).toFixed(1)}% — ${columns_resolved} of ` +
    `${columns_total} source column(s) resolved to a known field.`,
    { color: MUTED },
  );
  if (columns_unresolved > 0 || warning_count > 0) {
    bullet(
      doc, cursor,
      `${columns_unresolved} column(s) unresolved and ${warning_count} parse warning(s). ` +
      'Unresolved columns are excluded from every figure above rather than guessed at.',
      { color: MUTED },
    );
  } else {
    bullet(doc, cursor, 'No unresolved columns or parse warnings.', { color: MUTED });
  }
}

// ══════════════════════════════════════════════════════════════════════════
//  Footer
// ══════════════════════════════════════════════════════════════════════════

function stampFooters(doc: Doc, report: QaReport) {
  const pages = doc.internal.getNumberOfPages();
  for (let p = 1; p <= pages; p++) {
    doc.setPage(p);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    setColor(doc, 'setTextColor', MUTED);
    doc.text(`QA Insights · ${report.stats.ingest.source_label}`, MARGIN, FOOTER_Y);
    doc.text(`Page ${p} of ${pages}`, PAGE_W - MARGIN, FOOTER_Y, { align: 'right' });
  }
}
