/**
 * The QA agent's control panel, rendered above the qa-insights grid.
 *
 * Two things the dashboard grid cannot express, because neither is a metric:
 *
 *   Ingest  drop a workbook, watch it parse, see what the mapper resolved and
 *           what it could not, then run the analysis with live stage progress.
 *   Chat    ask the snapshot a question and get an answer with the SQL that
 *           produced it.
 *
 * Both collapse to a single status strip when idle, so the dashboard stays the
 * thing on screen and the console is there when it is wanted.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Calendar, ChevronDown, ChevronRight, CircleCheck, CircleDashed, Clock,
  Database, Download, History, LoaderCircle, MessageSquare, Play, Plus,
  Power, PowerOff, Send, Trash2, TriangleAlert, Upload, Zap,
} from 'lucide-react';

import { API_BASE } from './api';
import { downloadQaReportPdf } from './qa-report-pdf';
import { useFilterActions, useFilters } from './filters';

// ══════════════════════════════════════════════════════════════════════════
//  Types
// ══════════════════════════════════════════════════════════════════════════

interface Health {
  ok: boolean;
  snapshot_id: string | null;
  has_snapshot: boolean;
  has_report: boolean;
  model_configured: boolean;
  model_reachable: boolean;
  model: string | null;
}

interface SheetProbe {
  name: string;
  role: string;
  shape: string;
  row_count: number;
  columns: { field: string | null; header: string | null; note?: string | null }[];
}

interface IngestSummary {
  snapshot_id: string;
  source_kind: string;
  source_label: string;
  bug_count: number;
  test_case_count: number;
  matrix_result_count: number;
  warnings: string[];
  sheets: SheetProbe[];
  source_files: {
    name: string; ok: boolean; error: string | null;
    bugs: number; test_cases: number; matrix_results: number;
  }[];
}

interface ChatTurn {
  question: string;
  answer: string;
  sql: string;
  rows: Record<string, unknown>[];
  row_count: number;
  entity: string;
  used_model: boolean;
  error?: string | null;
  pending?: boolean;
}

const STAGES = ['stats', 'findings', 'narration'] as const;

// ══════════════════════════════════════════════════════════════════════════
//  Shell
// ══════════════════════════════════════════════════════════════════════════

type Tab = 'ingest' | 'chat' | 'schedules' | 'history' | null;

interface Schedule {
  id: string;
  label: string;
  source_label: string;
  cadence: 'daily' | 'weekly';
  run_at_hour: number;
  run_at_minute: number;
  weekday: number | null;
  window_mode: string;
  enabled: boolean;
  created_at: string;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  next_run_at: string;
  run_count: number;
}

interface ScheduleRun {
  id: string;
  ran_at: string;
  status: string;
  error: string | null;
  report_id: string | null;
  snapshot_id: string | null;
  verdict: string | null;
  headline: string | null;
}

interface ReportHistoryRow {
  id: string;
  snapshot_id: string;
  generated_at: string;
  partial: boolean;
  model_enabled: boolean;
  model_name: string | null;
  verdict: string | null;
  headline: string | null;
  counts: { critical: number; warning: number; info: number };
  source_label?: string;
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const VERDICT_DOT: Record<string, string> = {
  healthy: 'text-emerald-400', caution: 'text-amber-400',
  at_risk: 'text-orange-400', blocked: 'text-red-400',
};

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

export function QaConsole() {
  const [tab, setTab] = useState<Tab>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const qc = useQueryClient();
  const filters = useFilters();
  const { setFilter } = useFilterActions();

  // The filter bar owns the range; the console just reads it, so "Run
  // analysis" can never disagree with what the dashboard is showing.
  const activeWindow = filters.date_scoped === '1'
    ? {
        from: new Date(filters.date_range_start).toISOString().slice(0, 10),
        to: new Date(filters.date_range_end).toISOString().slice(0, 10),
      }
    : null;

  // Same principle for the dimension dropdowns: whichever ones the reader
  // has set on the filter bar go into the analysis request too, so the
  // narrated findings describe the same slice the tiles are showing rather
  // than a stale whole-snapshot picture sitting beside a filtered dashboard.
  const ENTITY_FILTER_PARAMS = [
    'severity', 'status', 'issue_type', 'module',
    'test_status', 'test_priority', 'reporter',
  ] as const;
  const entityFilters = Object.fromEntries(
    ENTITY_FILTER_PARAMS
      .map(p => [p, filters[p]])
      .filter(([, v]) => v),
  ) as Partial<Record<typeof ENTITY_FILTER_PARAMS[number], string>>;

  const { data: health } = useQuery<Health>({
    // Keyed by the snapshot on screen, not a fixed string — health is a
    // per-snapshot question ("is THIS one analyzed?"), and a stale answer for
    // the one you just switched away from must not linger under a shared key.
    queryKey: ['qa-health', filters.snapshot_id],
    queryFn: async () => {
      const qs = filters.snapshot_id
        ? `?snapshot_id=${encodeURIComponent(filters.snapshot_id)}` : '';
      const res = await fetch(`${API_BASE}/api/qa/health${qs}`, { credentials: 'include' });
      if (!res.ok) throw new Error(`health failed (${res.status})`);
      return res.json();
    },
    // A poll, not just an invalidate-on-action. Analysis can also be kicked
    // off by a second browser tab or a curl call, and the badge should catch
    // up within one interval rather than needing the exact click that started
    // it to also be the one that clears its own cache.
    refetchInterval: 8000,
  });

  /**
   * Everything downstream of a new snapshot is stale — refetch it all.
   *
   * `snapshotId` matters more than the refetch. The snapshot dropdown writes
   * its choice to the URL, and a pinned snapshot does not move when a new file
   * is ingested — so uploading a workbook while an older one was selected
   * refetched every metric and changed nothing on screen, which reads exactly
   * like the ingest silently failed. Selecting the new snapshot is what makes
   * the upload visible.
   */
  const afterIngest = useCallback((snapshotId?: string) => {
    if (snapshotId) setFilter('snapshot_id', snapshotId);
    qc.invalidateQueries({ queryKey: ['metric'] });
    qc.invalidateQueries({ queryKey: ['capabilities'] });
    qc.invalidateQueries({ queryKey: ['dimension'] });
    qc.invalidateQueries({ queryKey: ['qa-health'] });
  }, [qc, setFilter]);

  /**
   * Ask jsPDF (loaded on demand — see qa-report-pdf.ts) to build the report
   * for whatever snapshot is on screen and save it. A 404 here almost always
   * means "not analyzed yet", so that's surfaced as the error rather than a
   * generic failure — the fix is the Ingest panel's Run analysis, not a retry.
   */
  const downloadReport = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadQaReportPdf(API_BASE, filters.snapshot_id);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 flex-wrap">
        <TabButton active={tab === 'ingest'} onClick={() => setTab(t => t === 'ingest' ? null : 'ingest')}
                   icon={Upload} label="Ingest data" />
        <TabButton active={tab === 'chat'} onClick={() => setTab(t => t === 'chat' ? null : 'chat')}
                   icon={MessageSquare} label="Ask the data" />
        <TabButton active={tab === 'schedules'} onClick={() => setTab(t => t === 'schedules' ? null : 'schedules')}
                   icon={Clock} label="Schedules" />
        <TabButton active={tab === 'history'} onClick={() => setTab(t => t === 'history' ? null : 'history')}
                   icon={History} label="Report history" />

        <div className="ml-auto flex items-center gap-2">
          {downloadError && (
            <span className="text-[11px] text-amber-400">{downloadError}</span>
          )}
          <button
            onClick={downloadReport}
            disabled={downloading || !health?.has_report}
            title={!health?.has_report ? 'Run analysis first — this snapshot has no report yet.' : undefined}
            className="flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border border-neutral-700 bg-neutral-800 text-neutral-200 hover:bg-neutral-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {downloading
              ? <LoaderCircle size={13} className="animate-spin" />
              : <Download size={13} />}
            {downloading ? 'Preparing…' : 'Download report'}
          </button>
        </div>
      </div>

      {tab === 'ingest' && (
        <IngestPanel
          onDone={afterIngest}
          health={health}
          selectedSnapshot={filters.snapshot_id}
          window={activeWindow}
          entityFilters={entityFilters}
        />
      )}
      {tab === 'chat' && (
        <ChatPanel health={health} snapshotId={filters.snapshot_id} />
      )}
      {tab === 'schedules' && <SchedulesPanel />}
      {tab === 'history' && <ReportHistoryPanel snapshotId={filters.snapshot_id} />}
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label }: {
  active: boolean; onClick: () => void; icon: typeof Upload; label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border transition-colors',
        active
          ? 'bg-neutral-800 border-neutral-700 text-neutral-100'
          : 'bg-neutral-900 border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700',
      )}
    >
      <Icon size={13} strokeWidth={2} />
      {label}
      {active ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
    </button>
  );
}

function Panel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-2 bg-neutral-900 border border-neutral-800 rounded-xl p-4">
      {children}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  INGEST
// ══════════════════════════════════════════════════════════════════════════

function IngestPanel({ onDone, health, selectedSnapshot, window: dateWindow, entityFilters }: {
  onDone: (snapshotId?: string) => void;
  health?: Health;
  selectedSnapshot?: string;
  /** Inclusive yyyy-mm-dd pair when the user has scoped to a range. */
  window?: { from: string; to: string } | null;
  /** Whichever dimension dropdowns (severity, module, reporter, …) are set. */
  entityFilters?: Record<string, string>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<IngestSummary | null>(null);
  const [stages, setStages] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = async (fileList: File[]) => {
    if (fileList.length === 0) return;
    setBusy(fileList.length === 1
      ? 'Parsing workbook…'
      : `Parsing ${fileList.length} workbooks…`);
    setError(null); setSummary(null); setStages({});
    try {
      // One request, many files — they become ONE snapshot, which is what
      // lets the agent reason across a test plan and its bug tracker rather
      // than reporting on each in isolation.
      const body = new FormData();
      for (const f of fileList) body.append('files', f);
      const res = await fetch(`${API_BASE}/api/qa/ingest`, {
        method: 'POST', body, credentials: 'include',
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `ingest failed (${res.status})`);
      setSummary(json);
      onDone(json.snapshot_id);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(null);
    }
  };

  const ingestPostgres = async () => {
    setBusy('Reading Postgres source…'); setError(null); setSummary(null); setStages({});
    try {
      const res = await fetch(`${API_BASE}/api/qa/ingest/postgres`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: '{}',
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `ingest failed (${res.status})`);
      setSummary(json);
      onDone(json.snapshot_id);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(null);
    }
  };

  /** Analysis streams its stages over SSE — a full run is slow enough with a
   *  model attached that a spinner alone would look hung. */
  const analyze = async () => {
    setBusy('Analyzing…'); setError(null);
    setStages(Object.fromEntries(STAGES.map(s => [s, 'pending'])));
    try {
      // Analyze what the user is LOOKING AT. Defaulting to "latest" meant
      // clicking Run analysis while an older snapshot was selected produced a
      // report for a different one, and the panel appeared to do nothing.
      // Analyse exactly what the filter bar says: this snapshot, and either
      // the whole set or the chosen window. Sending the range here is what
      // makes "analyse this date range" mean the report too, not just the
      // dashboard tiles.
      const params = new URLSearchParams();
      if (selectedSnapshot) params.set('snapshot_id', selectedSnapshot);
      if (dateWindow) {
        params.set('date_from', dateWindow.from);
        params.set('date_to', dateWindow.to);
      }
      for (const [k, v] of Object.entries(entityFilters ?? {})) params.set(k, v);
      const qs = params.toString() ? `?${params}` : '';
      const res = await fetch(`${API_BASE}/api/qa/analyze${qs}`, {
        method: 'POST', credentials: 'include',
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `analyze failed (${res.status})`);

      await new Promise<void>((resolve, reject) => {
        const es = new EventSource(`${API_BASE}/api/qa/analyze/${json.job_id}/events`);
        es.onmessage = ev => {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'stage') {
            setStages(s => ({ ...s, [msg.stage]: msg.status }));
          } else if (msg.type === 'end') {
            es.close();
            msg.status === 'error' ? reject(new Error(msg.error)) : resolve();
          }
        };
        es.onerror = () => { es.close(); reject(new Error('progress stream dropped')); };
      });
      onDone(json.snapshot_id);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel>
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => {
          e.preventDefault(); setDragging(false);
          upload(Array.from(e.dataTransfer.files ?? []));
        }}
        onClick={() => fileRef.current?.click()}
        className={clsx(
          'border border-dashed rounded-lg px-4 py-6 text-center cursor-pointer transition-colors',
          dragging
            ? 'border-neutral-500 bg-neutral-800/40'
            : 'border-neutral-700 hover:border-neutral-600 hover:bg-neutral-800/20',
        )}
      >
        <Upload size={16} className="mx-auto text-neutral-500 mb-1.5" />
        <div className="text-[13px] text-neutral-300">
          Drop QA workbooks here, or click to choose
        </div>
        <div className="text-[11px] text-neutral-600 mt-0.5">
          .xlsx or .xlsm — several files become one analysis set, each still
          tagged with the file it came from
        </div>
        <input
          ref={fileRef} type="file" accept=".xlsx,.xlsm" multiple className="hidden"
          onChange={e => { upload(Array.from(e.target.files ?? [])); e.target.value = ''; }}
        />
      </div>

      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <button
          onClick={ingestPostgres} disabled={!!busy}
          className="flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border border-neutral-800 bg-neutral-900 text-neutral-300 hover:border-neutral-700 disabled:opacity-40"
        >
          <Database size={13} /> Read Postgres source
        </button>
        <button
          onClick={analyze} disabled={!!busy || !health?.has_snapshot}
          className="flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border border-emerald-900/70 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/15 disabled:opacity-40"
        >
          <Play size={13} />
          {dateWindow ? `Run analysis · ${dateWindow.from} to ${dateWindow.to}` : 'Run analysis'}
        </button>
        {busy && <span className="text-[12px] text-neutral-400">{busy}</span>}
      </div>

      {Object.keys(stages).length > 0 && (
        <div className="flex items-center gap-4 mt-3">
          {STAGES.map(s => {
            const st = stages[s];
            return (
              <span key={s} className={clsx(
                'flex items-center gap-1.5 text-[11px]',
                st === 'done' ? 'text-emerald-400'
                  : st === 'running' ? 'text-neutral-200' : 'text-neutral-600',
              )}>
                {st === 'done'
                  ? <CircleCheck size={12} />
                  : <CircleDashed size={12} className={st === 'running' ? 'animate-spin' : ''} />}
                {s}
              </span>
            );
          })}
        </div>
      )}

      {error && (
        <div className="mt-3 text-[12px] text-red-300 bg-red-950/30 border border-red-900 rounded-md p-2.5">
          {error}
        </div>
      )}

      {summary && <IngestReceipt summary={summary} />}
    </Panel>
  );
}

/**
 * What the mapper actually understood. Shown because every number on the
 * dashboard is conditional on this having gone right, and an unresolved column
 * is the difference between "no bugs of that type" and "we could not read it".
 */
function IngestReceipt({ summary }: { summary: IngestSummary }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="mt-3 border-t border-neutral-800 pt-3">
      <div className="flex items-center gap-4 flex-wrap text-[12px]">
        <span className="text-neutral-200 font-medium">{summary.source_label}</span>
        <Stat n={summary.bug_count} label="bugs" />
        <Stat n={summary.test_case_count} label="test cases" />
        <Stat n={summary.matrix_result_count} label="matrix cells" />
        {summary.warnings.length > 0 && (
          <span className="flex items-center gap-1 text-amber-400">
            <TriangleAlert size={12} /> {summary.warnings.length} warning
            {summary.warnings.length === 1 ? '' : 's'}
          </span>
        )}
        <button onClick={() => setOpen(o => !o)}
                className="ml-auto text-[11px] text-neutral-500 hover:text-neutral-300 underline">
          {open ? 'Hide detail' : 'What was read?'}
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-3">
          {summary.source_files?.length > 1 && (
            // Per file, before per sheet. With several files in one snapshot
            // "which file did this come from" is the first question, and a
            // file that failed to parse only appears here — it contributes no
            // sheets to the table below.
            <table className="text-[11px] w-full">
              <thead>
                <tr className="text-neutral-500 text-left">
                  <th className="font-normal pb-1">File</th>
                  <th className="font-normal pb-1 text-right">Bugs</th>
                  <th className="font-normal pb-1 text-right">Test cases</th>
                  <th className="font-normal pb-1 text-right">Matrix cells</th>
                </tr>
              </thead>
              <tbody>
                {summary.source_files.map(f => (
                  <tr key={f.name} className={f.ok ? 'text-neutral-300' : 'text-red-300'}>
                    <td className="py-0.5">
                      {f.name}
                      {!f.ok && <span className="text-red-400"> — {f.error}</span>}
                    </td>
                    <td className="py-0.5 text-right">{f.bugs}</td>
                    <td className="py-0.5 text-right">{f.test_cases}</td>
                    <td className="py-0.5 text-right">{f.matrix_results}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <table className="text-[11px] w-full">
            <thead>
              <tr className="text-neutral-500 text-left">
                <th className="font-normal pb-1">Sheet</th>
                <th className="font-normal pb-1">Read as</th>
                <th className="font-normal pb-1">Shape</th>
                <th className="font-normal pb-1 text-right">Rows</th>
                <th className="font-normal pb-1 text-right">Columns resolved</th>
              </tr>
            </thead>
            <tbody>
              {summary.sheets.map(s => {
                const resolved = s.columns.filter(c => c.field).length;
                return (
                  <tr key={s.name} className="text-neutral-300">
                    <td className="py-0.5">{s.name}</td>
                    <td className="py-0.5 text-neutral-400">{s.role}</td>
                    <td className="py-0.5 text-neutral-500">{s.shape}</td>
                    <td className="py-0.5 text-right">{s.row_count}</td>
                    <td className={clsx('py-0.5 text-right',
                      resolved < s.columns.length ? 'text-amber-400' : 'text-neutral-300')}>
                      {resolved}/{s.columns.length}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {summary.warnings.length > 0 && (
            <ul className="space-y-1">
              {summary.warnings.map((w, i) => (
                <li key={i} className="flex gap-2 text-[11px] text-amber-300/90">
                  <TriangleAlert size={11} className="shrink-0 mt-0.5" />
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <span className="text-neutral-400">
      <span className="text-neutral-100 font-medium">{n.toLocaleString()}</span> {label}
    </span>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  CHAT
// ══════════════════════════════════════════════════════════════════════════

const SUGGESTIONS = [
  'Which localization bugs are still open?',
  'What test cases have never been run?',
  'Show me open blockers',
  'Any bugs mentioning wall placement?',
  'Which strings fail in French?',
];

function ChatPanel({ health, snapshotId }: { health?: Health; snapshotId?: string }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [turns]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setInput('');
    setBusy(true);
    setTurns(t => [...t, {
      question, answer: '', sql: '', rows: [], row_count: 0,
      entity: '', used_model: false, pending: true,
    }]);
    try {
      const res = await fetch(`${API_BASE}/api/qa/chat`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, snapshot_id: snapshotId }),
      });
      const json = await res.json();
      setTurns(t => [...t.slice(0, -1), {
        question,
        answer: json.answer ?? json.detail ?? 'No answer.',
        sql: json.sql ?? '', rows: json.rows ?? [], row_count: json.row_count ?? 0,
        entity: json.entity ?? '', used_model: json.used_model ?? false,
        error: json.error,
      }]);
    } catch (e) {
      setTurns(t => [...t.slice(0, -1), {
        question, answer: `Request failed: ${e}`, sql: '', rows: [],
        row_count: 0, entity: '', used_model: false, error: 'request_failed',
      }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      {!health?.model_configured && (
        <div className="mb-3 text-[12px] text-amber-300/90 bg-amber-950/25 border border-amber-900/60 rounded-md p-2.5">
          No model is configured, so questions can't be compiled into a query.
          Set <code className="text-amber-200">OLLAMA_HOST</code> and restart the
          backend. The dashboard and findings work without it.
        </div>
      )}

      <div className="max-h-[420px] overflow-y-auto space-y-3">
        {turns.length === 0 && (
          <p className="text-[13px] text-neutral-500 py-4 text-center">
            Ask about bugs, test coverage, or localization. Every answer is
            grounded in a real query, shown beneath it.
          </p>
        )}
        {turns.map((t, i) => <ChatTurnView key={i} turn={t} />)}
        <div ref={endRef} />
      </div>

      <div className="flex flex-wrap gap-1.5 mt-3">
        {SUGGESTIONS.map(s => (
          <button
            key={s} onClick={() => ask(s)} disabled={busy}
            className="text-[11px] px-2 py-1 rounded-full border border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700 disabled:opacity-40"
          >
            {s}
          </button>
        ))}
      </div>

      <form
        onSubmit={e => { e.preventDefault(); ask(input); }}
        className="flex items-center gap-2 mt-2"
      >
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about bugs, coverage, or localization…"
          className="flex-1 bg-neutral-950 border border-neutral-800 rounded-md px-3 py-2 text-[13px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-700"
        />
        <button
          type="submit" disabled={busy || !input.trim()}
          className="flex items-center gap-1.5 text-[12px] px-3 py-2 rounded-md border border-neutral-700 bg-neutral-800 text-neutral-200 hover:bg-neutral-700 disabled:opacity-40"
        >
          <Send size={13} /> Ask
        </button>
      </form>
    </Panel>
  );
}

function ChatTurnView({ turn }: { turn: ChatTurn }) {
  const [showRows, setShowRows] = useState(false);
  const cols = turn.rows.length ? Object.keys(turn.rows[0]) : [];

  return (
    <div className="space-y-1.5">
      <div className="text-[13px] text-neutral-100 font-medium">{turn.question}</div>

      {turn.pending ? (
        <div className="text-[13px] text-neutral-500 flex items-center gap-2">
          <CircleDashed size={13} className="animate-spin" /> compiling a query…
        </div>
      ) : (
        <>
          <p className={clsx('text-[13px] leading-relaxed',
            turn.error ? 'text-amber-300/90' : 'text-neutral-300')}>
            {turn.answer}
          </p>

          {turn.sql && (
            <div className="text-[11px]">
              <div className="flex items-center gap-2 text-neutral-600">
                <span className="font-mono">
                  {turn.entity} · {turn.row_count} row{turn.row_count === 1 ? '' : 's'}
                </span>
                {!turn.used_model && <span className="text-amber-500">· not narrated</span>}
                {turn.rows.length > 0 && (
                  <button onClick={() => setShowRows(s => !s)}
                          className="underline hover:text-neutral-400">
                    {showRows ? 'hide rows' : 'show rows'}
                  </button>
                )}
              </div>
              <pre className="mt-1 bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-x-auto text-neutral-500 font-mono whitespace-pre-wrap">
                {turn.sql}
              </pre>
            </div>
          )}

          {showRows && turn.rows.length > 0 && (
            <div className="overflow-x-auto border border-neutral-800 rounded-md">
              <table className="text-[11px] w-full">
                <thead className="bg-neutral-950">
                  <tr className="text-neutral-500 text-left">
                    {cols.map(c => (
                      <th key={c} className="font-normal px-2 py-1 whitespace-nowrap">
                        {c.replace(/_/g, ' ')}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {turn.rows.map((r, i) => (
                    <tr key={i} className="text-neutral-300 border-t border-neutral-800/70">
                      {cols.map(c => (
                        <td key={c} className="px-2 py-1 max-w-[300px] truncate">
                          {r[c] == null ? '—' : String(r[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  SCHEDULES — recurring analysis, run in the background without a click
// ══════════════════════════════════════════════════════════════════════════

function SchedulesPanel() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data } = useQuery<{ schedules: Schedule[] }>({
    queryKey: ['qa-schedules'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/qa/schedules`, { credentials: 'include' });
      if (!res.ok) throw new Error(`schedules failed (${res.status})`);
      return res.json();
    },
    // A schedule can also fire on its own between clicks — poll so a run
    // that happened while this tab sat closed shows up without a refresh.
    refetchInterval: 30000,
  });
  const schedules = data?.schedules ?? [];

  const { data: snapshotsData } = useQuery<{ snapshots: { source_label: string }[] }>({
    queryKey: ['qa-snapshots-for-schedules'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/qa/snapshots`, { credentials: 'include' });
      if (!res.ok) throw new Error(`snapshots failed (${res.status})`);
      return res.json();
    },
  });
  const sourceLabels = Array.from(
    new Set((snapshotsData?.snapshots ?? []).map(s => s.source_label)),
  );

  const withBusy = (id: string, fn: () => Promise<void>) => async () => {
    setBusyId(id); setError(null);
    try {
      await fn();
      qc.invalidateQueries({ queryKey: ['qa-schedules'] });
      qc.invalidateQueries({ queryKey: ['qa-schedule-runs', id] });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusyId(null);
    }
  };

  const runNow = (id: string) => withBusy(id, async () => {
    const res = await fetch(`${API_BASE}/api/qa/schedules/${id}/run-now`, {
      method: 'POST', credentials: 'include',
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail ?? `run-now failed (${res.status})`);
    qc.invalidateQueries({ queryKey: ['qa-reports'] });
  });

  const toggleEnabled = (s: Schedule) => withBusy(s.id, async () => {
    const res = await fetch(
      `${API_BASE}/api/qa/schedules/${s.id}/enable?enabled=${!s.enabled}`,
      { method: 'POST', credentials: 'include' },
    );
    if (!res.ok) throw new Error(`enable failed (${res.status})`);
  });

  const remove = (id: string) => withBusy(id, async () => {
    const res = await fetch(`${API_BASE}/api/qa/schedules/${id}`, {
      method: 'DELETE', credentials: 'include',
    });
    if (!res.ok) throw new Error(`delete failed (${res.status})`);
  });

  return (
    <Panel>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[12px] text-neutral-500">
          Recurring analysis — daily or weekly — against the latest snapshot
          matching a source, on its own, no click required. Only fires while
          this backend process stays running; a restart does not lose a
          schedule, but does lose whatever would have fired while it was down.
        </p>
        <button
          onClick={() => setShowCreate(s => !s)}
          className="flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border border-neutral-700 bg-neutral-800 text-neutral-200 hover:bg-neutral-700 shrink-0"
        >
          <Plus size={13} /> New schedule
        </button>
      </div>

      {showCreate && (
        <CreateScheduleForm
          sourceLabels={sourceLabels}
          onCreated={() => {
            setShowCreate(false);
            qc.invalidateQueries({ queryKey: ['qa-schedules'] });
          }}
          onError={setError}
        />
      )}

      {error && (
        <div className="mt-3 text-[12px] text-red-300 bg-red-950/30 border border-red-900 rounded-md p-2.5">
          {error}
        </div>
      )}

      <div className="mt-3 space-y-2">
        {schedules.length === 0 && (
          <p className="text-[13px] text-neutral-500 py-4 text-center">
            No schedules yet — create one to have analysis run on its own.
          </p>
        )}
        {schedules.map(s => (
          <ScheduleRow
            key={s.id}
            schedule={s}
            busy={busyId === s.id}
            expanded={expanded === s.id}
            onToggleExpand={() => setExpanded(e => e === s.id ? null : s.id)}
            onRunNow={runNow(s.id)}
            onToggleEnabled={toggleEnabled(s)}
            onDelete={remove(s.id)}
          />
        ))}
      </div>
    </Panel>
  );
}

function CreateScheduleForm({ sourceLabels, onCreated, onError }: {
  sourceLabels: string[];
  onCreated: () => void;
  onError: (e: string | null) => void;
}) {
  const [label, setLabel] = useState('');
  const [sourceLabel, setSourceLabel] = useState('');
  const [cadence, setCadence] = useState<'daily' | 'weekly'>('daily');
  const [hour, setHour] = useState(6);
  const [minute, setMinute] = useState(0);
  const [weekday, setWeekday] = useState(0);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!label.trim() || !sourceLabel.trim()) {
      onError('Label and source are both required.');
      return;
    }
    setBusy(true); onError(null);
    try {
      const res = await fetch(`${API_BASE}/api/qa/schedules`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: label.trim(),
          source_label: sourceLabel.trim(),
          cadence,
          run_at_hour: hour,
          run_at_minute: minute,
          weekday: cadence === 'weekly' ? weekday : null,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? `create failed (${res.status})`);
      setLabel(''); setSourceLabel('');
      onCreated();
    } catch (e2) {
      onError(String(e2 instanceof Error ? e2.message : e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="mt-3 border-t border-neutral-800 pt-3 flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-1">
        <span className="text-[11px] text-neutral-500">Label</span>
        <input
          value={label} onChange={e => setLabel(e.target.value)}
          placeholder="Monday QA report"
          className="bg-neutral-950 border border-neutral-800 rounded-md px-2 py-1.5 text-[12px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-700 w-40"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[11px] text-neutral-500">Source</span>
        <input
          value={sourceLabel} onChange={e => setSourceLabel(e.target.value)}
          list="qa-source-labels" placeholder="Source label"
          className="bg-neutral-950 border border-neutral-800 rounded-md px-2 py-1.5 text-[12px] text-neutral-200 placeholder:text-neutral-600 focus:outline-none focus:border-neutral-700 w-48"
        />
        <datalist id="qa-source-labels">
          {sourceLabels.map(l => <option key={l} value={l} />)}
        </datalist>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[11px] text-neutral-500">Cadence</span>
        <select
          value={cadence} onChange={e => setCadence(e.target.value as 'daily' | 'weekly')}
          className="bg-neutral-950 border border-neutral-800 rounded-md px-2 py-1.5 text-[12px] text-neutral-200 focus:outline-none focus:border-neutral-700"
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
        </select>
      </label>
      {cadence === 'weekly' && (
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-neutral-500">Weekday</span>
          <select
            value={weekday} onChange={e => setWeekday(Number(e.target.value))}
            className="bg-neutral-950 border border-neutral-800 rounded-md px-2 py-1.5 text-[12px] text-neutral-200 focus:outline-none focus:border-neutral-700"
          >
            {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
        </label>
      )}
      <label className="flex flex-col gap-1">
        <span className="text-[11px] text-neutral-500">Time (UTC)</span>
        <div className="flex items-center gap-1">
          <input
            type="number" min={0} max={23} value={hour}
            onChange={e => setHour(Number(e.target.value))}
            className="bg-neutral-950 border border-neutral-800 rounded-md px-2 py-1.5 text-[12px] text-neutral-200 w-14 focus:outline-none focus:border-neutral-700"
          />
          <span className="text-neutral-500">:</span>
          <input
            type="number" min={0} max={59} value={minute}
            onChange={e => setMinute(Number(e.target.value))}
            className="bg-neutral-950 border border-neutral-800 rounded-md px-2 py-1.5 text-[12px] text-neutral-200 w-14 focus:outline-none focus:border-neutral-700"
          />
        </div>
      </label>
      <button
        type="submit" disabled={busy}
        className="flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-md border border-emerald-900/70 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/15 disabled:opacity-40"
      >
        {busy ? <LoaderCircle size={13} className="animate-spin" /> : <Calendar size={13} />}
        Create
      </button>
    </form>
  );
}

function ScheduleRow({ schedule, busy, expanded, onToggleExpand, onRunNow, onToggleEnabled, onDelete }: {
  schedule: Schedule;
  busy: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  onRunNow: () => void;
  onToggleEnabled: () => void;
  onDelete: () => void;
}) {
  const cadenceLabel = schedule.cadence === 'weekly'
    ? `Weekly · ${WEEKDAYS[schedule.weekday ?? 0]} ${pad2(schedule.run_at_hour)}:${pad2(schedule.run_at_minute)} UTC`
    : `Daily · ${pad2(schedule.run_at_hour)}:${pad2(schedule.run_at_minute)} UTC`;

  return (
    <div className={clsx(
      'border rounded-md px-3 py-2',
      schedule.enabled ? 'border-neutral-800' : 'border-neutral-800/50 opacity-60',
    )}>
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={onToggleExpand} className="text-neutral-500 hover:text-neutral-300 shrink-0">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <div className="min-w-0">
          <div className="text-[13px] text-neutral-100 font-medium truncate">{schedule.label}</div>
          <div className="text-[11px] text-neutral-500 truncate">
            {schedule.source_label} · {cadenceLabel}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-neutral-500 shrink-0">
          {schedule.last_status && (
            <span className={clsx(
              'flex items-center gap-1',
              schedule.last_status === 'ok' ? 'text-emerald-400' : 'text-red-400',
            )}>
              {schedule.last_status === 'ok'
                ? <CircleCheck size={12} />
                : <TriangleAlert size={12} />}
              last run {schedule.last_run_at ? new Date(schedule.last_run_at).toLocaleString() : '—'}
            </span>
          )}
          <span>next {new Date(schedule.next_run_at).toLocaleString()}</span>
          <span>{schedule.run_count} run{schedule.run_count === 1 ? '' : 's'}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <IconButton title="Run now" onClick={onRunNow} disabled={busy}>
            {busy ? <LoaderCircle size={13} className="animate-spin" /> : <Zap size={13} />}
          </IconButton>
          <IconButton title={schedule.enabled ? 'Disable' : 'Enable'} onClick={onToggleEnabled} disabled={busy}>
            {schedule.enabled ? <PowerOff size={13} /> : <Power size={13} />}
          </IconButton>
          <IconButton title="Delete" onClick={onDelete} disabled={busy} danger>
            <Trash2 size={13} />
          </IconButton>
        </div>
      </div>

      {schedule.last_error && (
        <div className="mt-1.5 text-[11px] text-amber-300/90 pl-6">{schedule.last_error}</div>
      )}

      {expanded && <ScheduleRunHistory scheduleId={schedule.id} />}
    </div>
  );
}

function IconButton({ title, onClick, disabled, danger, children }: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      title={title} onClick={onClick} disabled={disabled}
      className={clsx(
        'p-1.5 rounded-md border disabled:opacity-40',
        danger
          ? 'border-red-900/60 text-red-400 hover:bg-red-950/30'
          : 'border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700',
      )}
    >
      {children}
    </button>
  );
}

function ScheduleRunHistory({ scheduleId }: { scheduleId: string }) {
  const { data, isLoading } = useQuery<{ runs: ScheduleRun[] }>({
    queryKey: ['qa-schedule-runs', scheduleId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/api/qa/schedules/${scheduleId}/runs`, { credentials: 'include' });
      if (!res.ok) throw new Error(`runs failed (${res.status})`);
      return res.json();
    },
  });
  const runs = data?.runs ?? [];

  return (
    <div className="mt-2 pl-6 border-t border-neutral-800/70 pt-2">
      {isLoading && <p className="text-[11px] text-neutral-600">Loading runs…</p>}
      {!isLoading && runs.length === 0 && (
        <p className="text-[11px] text-neutral-600">No runs yet.</p>
      )}
      {runs.length > 0 && (
        <table className="text-[11px] w-full">
          <thead>
            <tr className="text-neutral-500 text-left">
              <th className="font-normal pb-1">Ran</th>
              <th className="font-normal pb-1">Status</th>
              <th className="font-normal pb-1">Verdict</th>
              <th className="font-normal pb-1">Headline</th>
            </tr>
          </thead>
          <tbody>
            {runs.map(r => (
              <tr key={r.id} className="text-neutral-300 border-t border-neutral-800/50">
                <td className="py-1 whitespace-nowrap">{new Date(r.ran_at).toLocaleString()}</td>
                <td className="py-1">
                  <span className={r.status === 'ok' ? 'text-emerald-400' : 'text-red-400'}>
                    {r.status}
                  </span>
                </td>
                <td className="py-1">
                  {r.verdict && (
                    <span className={VERDICT_DOT[r.verdict] ?? 'text-neutral-400'}>{r.verdict}</span>
                  )}
                </td>
                <td className="py-1 text-neutral-400 max-w-[300px] truncate">
                  {r.error ? <span className="text-amber-300/90">{r.error}</span> : (r.headline ?? '—')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
//  REPORT HISTORY — every past report, manual or scheduled
// ══════════════════════════════════════════════════════════════════════════

function ReportHistoryPanel({ snapshotId }: { snapshotId?: string }) {
  const [scope, setScope] = useState<'this' | 'all'>('this');
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const effectiveSnapshotId = scope === 'this' ? snapshotId : undefined;

  const { data, isLoading } = useQuery<{ reports: ReportHistoryRow[] }>({
    queryKey: ['qa-reports', effectiveSnapshotId],
    queryFn: async () => {
      const qs = effectiveSnapshotId ? `?snapshot_id=${encodeURIComponent(effectiveSnapshotId)}` : '';
      const res = await fetch(`${API_BASE}/api/qa/reports${qs}`, { credentials: 'include' });
      if (!res.ok) throw new Error(`reports failed (${res.status})`);
      return res.json();
    },
  });
  const reports = data?.reports ?? [];

  const download = async (id: string) => {
    setDownloadingId(id); setError(null);
    try {
      // reportId pins the PDF to this exact historical row, not "latest".
      await downloadQaReportPdf(API_BASE, undefined, id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <Panel>
      <div className="flex items-center justify-between gap-3 mb-3">
        <p className="text-[12px] text-neutral-500">
          Every past report — manual and scheduled — newest first. Download any
          one to see exactly what was reported at that moment, not just today's.
        </p>
        <div className="flex items-center gap-1 text-[11px] shrink-0">
          <button
            onClick={() => setScope('this')}
            disabled={!snapshotId}
            className={clsx(
              'px-2 py-1 rounded-md border',
              scope === 'this'
                ? 'border-neutral-700 bg-neutral-800 text-neutral-200'
                : 'border-neutral-800 text-neutral-500 hover:text-neutral-300',
              !snapshotId && 'opacity-40 cursor-not-allowed',
            )}
          >
            This snapshot
          </button>
          <button
            onClick={() => setScope('all')}
            className={clsx(
              'px-2 py-1 rounded-md border',
              scope === 'all'
                ? 'border-neutral-700 bg-neutral-800 text-neutral-200'
                : 'border-neutral-800 text-neutral-500 hover:text-neutral-300',
            )}
          >
            All snapshots
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-3 text-[12px] text-red-300 bg-red-950/30 border border-red-900 rounded-md p-2.5">
          {error}
        </div>
      )}

      {isLoading && <p className="text-[13px] text-neutral-500 py-4 text-center">Loading…</p>}
      {!isLoading && reports.length === 0 && (
        <p className="text-[13px] text-neutral-500 py-4 text-center">
          No reports yet — run analysis, or wait for a schedule to fire.
        </p>
      )}

      {reports.length > 0 && (
        <div className="overflow-x-auto">
          <table className="text-[12px] w-full">
            <thead>
              <tr className="text-neutral-500 text-left">
                <th className="font-normal pb-1.5">Generated</th>
                {scope === 'all' && <th className="font-normal pb-1.5">Source</th>}
                <th className="font-normal pb-1.5">Verdict</th>
                <th className="font-normal pb-1.5">Headline</th>
                <th className="font-normal pb-1.5 text-right">Findings</th>
                <th className="font-normal pb-1.5" />
              </tr>
            </thead>
            <tbody>
              {reports.map(r => (
                <tr key={r.id} className="text-neutral-300 border-t border-neutral-800/70">
                  <td className="py-1.5 whitespace-nowrap">{new Date(r.generated_at).toLocaleString()}</td>
                  {scope === 'all' && (
                    <td className="py-1.5 text-neutral-400 max-w-[160px] truncate">{r.source_label}</td>
                  )}
                  <td className="py-1.5">
                    <span className={VERDICT_DOT[r.verdict ?? ''] ?? 'text-neutral-400'}>
                      {r.verdict ?? '—'}
                    </span>
                    {r.partial && (
                      <span
                        className="ml-1.5 text-amber-500"
                        title="Narration fell back to the deterministic summary"
                      >
                        · partial
                      </span>
                    )}
                  </td>
                  <td className="py-1.5 text-neutral-300 max-w-[360px] truncate">{r.headline ?? '—'}</td>
                  <td className="py-1.5 text-right text-neutral-400 whitespace-nowrap">
                    {r.counts?.critical ?? 0}c / {r.counts?.warning ?? 0}w / {r.counts?.info ?? 0}i
                  </td>
                  <td className="py-1.5 text-right">
                    <button
                      onClick={() => download(r.id)}
                      disabled={downloadingId === r.id}
                      className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-neutral-800 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700 disabled:opacity-40 ml-auto"
                    >
                      {downloadingId === r.id
                        ? <LoaderCircle size={12} className="animate-spin" />
                        : <Download size={12} />}
                      PDF
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
