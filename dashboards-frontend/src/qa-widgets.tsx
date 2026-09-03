/**
 * Widgets for the QA reporting agent.
 *
 * Three shapes the existing primitives could not carry:
 *
 *   NarrativeWidget    the agent's executive summary, with its provenance
 *   FindingsWidget     ranked findings, each expanding to its own evidence
 *   StatusMatrixWidget a grid whose cells carry an outcome, not a magnitude
 *
 * They share `Card` / `CardHeader` / `Skeleton` / `ErrorState` with the rest of
 * the dashboard, so a QA panel and a token-usage panel are the same object on
 * screen.
 */
import { useState } from 'react';
import clsx from 'clsx';
import {
  AlertTriangle, ChevronDown, ChevronRight, CircleAlert, HelpCircle, Info,
  OctagonAlert, ShieldCheck, Sparkles,
  type LucideIcon,
} from 'lucide-react';

import { useMetric } from './api';
import { Card, CardHeader, ErrorState, Skeleton } from './widgets';
import type {
  Finding, FindingsResponse, NarrativeResponse, StatusMatrixResponse,
} from './types';

// ══════════════════════════════════════════════════════════════════════════
//  Palettes
// ══════════════════════════════════════════════════════════════════════════

/**
 * Outcome vocabulary, shared by the test plan and the localization matrix.
 *
 * Pass is deliberately the quietest colour on the board. A matrix that is 95%
 * passing should read as calm so the eye lands on the cells that are not —
 * giving every outcome equal weight would make the healthy majority shout.
 */
const RESULT_COLORS: Record<string, { bg: string; fg: string; label: string }> = {
  'Pass':        { bg: 'rgba(52, 211, 153, 0.16)',  fg: '#6EE7B7', label: 'Pass' },
  'Fail':        { bg: 'rgba(248, 113, 113, 0.55)', fg: '#1A0A0A', label: 'Fail' },
  'Some Issue':  { bg: 'rgba(251, 191, 36, 0.45)',  fg: '#231A02', label: 'Issue' },
  'Blocked':     { bg: 'rgba(244, 114, 182, 0.45)', fg: '#2A0A1A', label: 'Blkd' },
  'In Progress': { bg: 'rgba(34, 211, 238, 0.35)',  fg: '#04222A', label: 'WIP' },
  'Not Run':     { bg: 'rgba(255, 255, 255, 0.05)', fg: '#737373', label: '—' },
  'Unknown':     { bg: 'rgba(255, 255, 255, 0.05)', fg: '#737373', label: '?' },
};
function resultColor(status: string) {
  return RESULT_COLORS[status] ?? RESULT_COLORS['Unknown'];
}

/**
 * The verdict is decided server-side by rule, never by the model. The palette
 * mirrors that: four fixed states and an explicit "not run", with nothing
 * in between for a summary to shade itself into.
 */
const VERDICT_META: Record<
  string,
  { label: string; icon: LucideIcon; cls: string; ring: string }
> = {
  healthy: { label: 'Healthy', icon: ShieldCheck,   cls: 'text-emerald-400', ring: 'border-emerald-800/60 bg-emerald-500/[0.06]' },
  caution: { label: 'Caution', icon: AlertTriangle, cls: 'text-amber-400',   ring: 'border-amber-800/60 bg-amber-500/[0.06]' },
  at_risk: { label: 'At risk', icon: CircleAlert,   cls: 'text-orange-400',  ring: 'border-orange-800/60 bg-orange-500/[0.06]' },
  blocked: { label: 'Blocked', icon: OctagonAlert,  cls: 'text-red-400',     ring: 'border-red-900/70 bg-red-500/[0.07]' },
  unknown: { label: 'Not run', icon: HelpCircle,    cls: 'text-neutral-400', ring: 'border-neutral-800' },
};

const LEVEL_META: Record<
  string,
  { icon: LucideIcon; cls: string; dot: string }
> = {
  critical: { icon: OctagonAlert,  cls: 'text-red-400',     dot: 'bg-red-500' },
  warning:  { icon: AlertTriangle, cls: 'text-amber-400',   dot: 'bg-amber-500' },
  info:     { icon: Info,          cls: 'text-neutral-400', dot: 'bg-neutral-500' },
};

/** Shown by both agent widgets before any analysis has been run. */
function AwaitingAnalysis({ hint }: { hint?: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-8 gap-2">
      <Sparkles size={18} className="text-neutral-600" />
      <p className="text-sm text-neutral-400">
        No analysis has been run for this snapshot yet.
      </p>
      <p className="text-xs text-neutral-600 max-w-md leading-relaxed">
        {hint ?? 'POST /api/qa/analyze to generate the report — this panel fills in when it finishes.'}
      </p>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  NARRATIVE
// ══════════════════════════════════════════════════════════════════════════

export function NarrativeWidget({ metric, title, emptyHint }: {
  metric: string; title: string; emptyHint?: string;
}) {
  const { data, isPending, error, refetch } = useMetric<NarrativeResponse>(metric);

  if (isPending) {
    return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[120px]" /></Card>;
  }
  if (error) {
    return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;
  }

  const verdict = VERDICT_META[data.verdict] ?? VERDICT_META.unknown;
  const VerdictIcon = verdict.icon;

  // How the summary was produced is part of the summary. A reader who cannot
  // tell narrated prose from a generated stand-in will trust both equally,
  // so the distinction is always on screen rather than in a log.
  const provenance = !data.model_enabled
    ? 'computed · no model configured'
    : data.partial
      ? `partial · ${data.model_name ?? 'model'} fell back`
      : `narrated by ${data.model_name ?? 'model'}`;

  return (
    <Card className={clsx('border', verdict.ring)}>
      <CardHeader
        title={title}
        right={data.available
          ? <span className="text-[11px] text-neutral-500 font-mono">{provenance}</span>
          : null}
      />

      {!data.available ? (
        <AwaitingAnalysis hint={emptyHint} />
      ) : (
        <div className="flex-1 flex flex-col gap-3 min-h-0">
          <div className="flex items-start gap-3">
            <div className={clsx('shrink-0 mt-0.5', verdict.cls)}>
              <VerdictIcon size={20} strokeWidth={2} />
            </div>
            <div className="min-w-0">
              <div className={clsx(
                'text-[10px] uppercase tracking-wider font-semibold mb-1',
                verdict.cls,
              )}>
                {verdict.label}
              </div>
              <p className="text-[15px] leading-snug text-neutral-100 font-medium">
                {data.headline || '—'}
              </p>
            </div>
          </div>

          {data.narrative && (
            <p className="text-[13px] leading-relaxed text-neutral-400">
              {data.narrative}
            </p>
          )}

          {data.sections?.length > 0 && (
            <div className="space-y-3 pt-1">
              {data.sections.map((s, i) => (
                <div key={i}>
                  <div className="text-[11px] uppercase tracking-wider text-neutral-500 mb-1">
                    {s.title}
                  </div>
                  <p className="text-[13px] leading-relaxed text-neutral-300">{s.body}</p>
                  {s.citations?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {s.citations.map(c => (
                        // Citations are rendered as chips so a reader can scan
                        // for "which ids does this claim rest on" without
                        // re-reading the prose that contains them.
                        <span key={c}
                              className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-neutral-700 bg-neutral-800/60 text-neutral-300">
                          {c}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {data.risks.length > 0 && (
            <div className="pt-2.5 border-t border-neutral-800/80">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1.5">
                Key risks
              </div>
              <ul className="space-y-1">
                {data.risks.map((risk, i) => (
                  <li key={i} className="flex gap-2 text-[13px] text-neutral-300 leading-snug">
                    <span className="text-neutral-600 select-none">·</span>
                    <span>{risk}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.recommendation && (
            <div className={clsx(
              'mt-auto pt-2.5 border-t border-neutral-800/80 flex gap-2 items-start',
            )}>
              <span className="text-[10px] uppercase tracking-wider text-neutral-500 shrink-0 mt-0.5">
                Next
              </span>
              <p className="text-[13px] text-neutral-200 leading-snug">
                {data.recommendation}
              </p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  FINDINGS
// ══════════════════════════════════════════════════════════════════════════

function FindingRow({ finding }: { finding: Finding }) {
  const [open, setOpen] = useState(false);
  const meta = LEVEL_META[finding.level] ?? LEVEL_META.info;
  const Icon = meta.icon;
  const hasEvidence = finding.evidence.length > 0;
  const evidenceKeys = hasEvidence ? Object.keys(finding.evidence[0]) : [];

  return (
    <li className="border-b border-neutral-800/70 last:border-b-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-2.5 py-2.5 text-left hover:bg-neutral-800/30"
      >
        <Icon size={14} className={clsx('shrink-0 mt-0.5', meta.cls)} strokeWidth={2} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] text-neutral-100 leading-snug">{finding.title}</div>
          {open && (
            <>
              <p className="text-[12px] text-neutral-500 mt-1 leading-relaxed">
                {finding.detail}
              </p>
              {finding.action && (
                // The action is the point of the finding, so it gets its own
                // treatment rather than blending into the explanation above it.
                <div className="mt-1.5 flex gap-1.5 items-start">
                  <span className="text-[9px] uppercase tracking-wider text-emerald-500/80 shrink-0 mt-[3px]">
                    Do
                  </span>
                  <p className="text-[12px] text-emerald-300/90 leading-relaxed">
                    {finding.action}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
        <span className="shrink-0 text-neutral-600 mt-0.5">
          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </span>
      </button>

      {open && hasEvidence && (
        <div className="pb-3 pl-6 pr-1 overflow-x-auto">
          <table className="text-[11px] w-full">
            <thead>
              <tr className="text-neutral-500">
                {evidenceKeys.map(k => (
                  <th key={k} className="text-left font-normal pr-4 pb-1 whitespace-nowrap">
                    {k.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {finding.evidence.map((row, i) => (
                <tr key={i} className="text-neutral-300 align-top">
                  {evidenceKeys.map(k => (
                    <td key={k} className="pr-4 py-0.5 max-w-[280px] truncate">
                      {row[k] == null ? '—' : String(row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </li>
  );
}

export function FindingsWidget({ metric, title, limit = 8, emptyHint }: {
  metric: string; title: string; limit?: number; emptyHint?: string;
}) {
  const { data, isPending, error, refetch } = useMetric<FindingsResponse>(metric);
  const [showAll, setShowAll] = useState(false);

  if (isPending) {
    return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[160px]" /></Card>;
  }
  if (error) {
    return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;
  }

  const shown = showAll ? data.findings : data.findings.slice(0, limit);
  const hidden = data.findings.length - limit;

  return (
    <Card>
      <CardHeader
        title={title}
        right={data.available ? (
          <div className="flex items-center gap-2.5">
            {(['critical', 'warning', 'info'] as const).map(level => (
              data.counts[level] > 0 ? (
                <span key={level} className="flex items-center gap-1 text-[11px] text-neutral-400">
                  <span className={clsx('w-1.5 h-1.5 rounded-full', LEVEL_META[level].dot)} />
                  {data.counts[level]}
                </span>
              ) : null
            ))}
          </div>
        ) : null}
      />

      {!data.available ? (
        <AwaitingAnalysis hint={emptyHint} />
      ) : data.findings.length === 0 ? (
        // An empty findings list is a result, not a missing one — every check
        // ran and none of them fired. Said plainly so it is not read as a bug.
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center py-8">
          <ShieldCheck size={18} className="text-emerald-500" />
          <p className="text-sm text-neutral-300">No findings — every check passed.</p>
          <p className="text-xs text-neutral-600">Silence here is a result, not an empty state.</p>
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <ul>
            {shown.map(f => <FindingRow key={f.id} finding={f} />)}
          </ul>
          {hidden > 0 && (
            <button
              onClick={() => setShowAll(s => !s)}
              className="mt-2 text-[11px] text-neutral-500 hover:text-neutral-300 underline"
            >
              {showAll ? 'Show fewer' : `Show ${hidden} more finding${hidden === 1 ? '' : 's'}`}
            </button>
          )}
        </div>
      )}
    </Card>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  STATUS MATRIX
// ══════════════════════════════════════════════════════════════════════════

export function StatusMatrixWidget({ metric, title, note }: {
  metric: string; title: string; note?: string;
}) {
  const { data, isPending, error, refetch } = useMetric<StatusMatrixResponse>(metric);

  if (isPending) {
    return <Card><CardHeader title={title} /><Skeleton className="flex-1 min-h-[200px]" /></Card>;
  }
  if (error) {
    return <Card><CardHeader title={title} /><ErrorState onRetry={() => refetch()} /></Card>;
  }

  if (data.rows.length === 0) {
    return (
      <Card>
        <CardHeader title={title} />
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center py-8">
          <ShieldCheck size={18} className="text-emerald-500" />
          <p className="text-sm text-neutral-300">
            Every checked string passes in every locale.
          </p>
          <p className="text-xs text-neutral-600">
            Only rows with a problem somewhere are listed here.
          </p>
        </div>
      </Card>
    );
  }

  // Only outcomes actually present get a legend entry — a legend listing
  // statuses that never occur is noise the reader has to filter out.
  const present = data.statuses.filter(s =>
    data.rows.some(r => Object.values(r.cells).includes(s)),
  );

  return (
    <Card>
      <CardHeader
        title={title}
        right={
          <div className="flex items-center gap-2.5 flex-wrap justify-end">
            {note && <span className="text-neutral-500">{note}</span>}
            {present.map(s => (
              <span key={s} className="flex items-center gap-1 text-[11px] text-neutral-400">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: resultColor(s).bg }} />
                {s}
              </span>
            ))}
          </div>
        }
      />

      <div className="overflow-auto flex-1">
        <div className="min-w-[620px]">
          <div className="flex items-end mb-1.5 sticky top-0 bg-neutral-900 z-10 pb-1">
            <div className="w-[26%] shrink-0 text-[10px] uppercase tracking-wider text-neutral-500 pl-1">
              Item
            </div>
            <div className="flex-1 flex gap-1">
              {data.columns.map(col => (
                <div key={col}
                     className="flex-1 text-center text-[10px] text-neutral-400 truncate px-0.5"
                     title={col}>
                  {col.slice(0, 8)}
                </div>
              ))}
            </div>
          </div>

          {data.rows.map(row => (
            <div key={row.item} className="flex items-center mb-1">
              <div className="w-[26%] shrink-0 pl-1 pr-2 min-w-0">
                <div className="text-[12px] text-neutral-300 truncate" title={row.item}>
                  {row.item}
                </div>
                {row.section && (
                  <div className="text-[10px] text-neutral-600 truncate">{row.section}</div>
                )}
              </div>
              <div className="flex-1 flex gap-1">
                {data.columns.map(col => {
                  const status = row.cells[col];
                  // A dimension this item was never checked against is not the
                  // same as one it failed — it gets no colour and no label.
                  if (!status) {
                    return (
                      <div key={col}
                           className="flex-1 h-7 rounded-sm"
                           style={{ background: 'rgba(255,255,255,0.02)' }}
                           title={`${row.item} · ${col}: not checked`} />
                    );
                  }
                  const c = resultColor(status);
                  return (
                    <div key={col}
                         className="flex-1 h-7 rounded-sm flex items-center justify-center text-[10px] font-semibold"
                         style={{ background: c.bg, color: c.fg }}
                         title={`${row.item} · ${col}: ${status}`}>
                      {c.label}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
