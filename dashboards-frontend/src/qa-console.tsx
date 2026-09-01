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
  ChevronDown, ChevronRight, CircleCheck, CircleDashed, Database,
  MessageSquare, Play, Send, TriangleAlert, Upload,
} from 'lucide-react';

import { API_BASE } from './api';
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

type Tab = 'ingest' | 'chat' | null;

export function QaConsole() {
  const [tab, setTab] = useState<Tab>(null);
  const qc = useQueryClient();
  const filters = useFilters();
  const { setFilter } = useFilterActions();

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

  const modelLabel = !health?.model_configured
    ? 'no model configured'
    : health.model_reachable
      ? (health.model ?? 'model ready')
      : `${health.model ?? 'model'} unreachable`;

  const modelTone = !health?.model_configured
    ? 'text-neutral-500 border-neutral-800'
    : health.model_reachable
      ? 'text-emerald-400 border-emerald-900/70'
      : 'text-amber-400 border-amber-900/70';

  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 flex-wrap">
        <TabButton active={tab === 'ingest'} onClick={() => setTab(t => t === 'ingest' ? null : 'ingest')}
                   icon={Upload} label="Ingest data" />
        <TabButton active={tab === 'chat'} onClick={() => setTab(t => t === 'chat' ? null : 'chat')}
                   icon={MessageSquare} label="Ask the data" />

        <div className="ml-auto flex items-center gap-2">
          <span className={clsx(
            'text-[11px] font-mono px-2 py-1 rounded-full border', modelTone,
          )}>
            {modelLabel}
          </span>
          {health?.has_snapshot && (
            <span className="text-[11px] font-mono px-2 py-1 rounded-full border border-neutral-800 text-neutral-500">
              {health.has_report ? 'analyzed' : 'not analyzed'}
            </span>
          )}
        </div>
      </div>

      {tab === 'ingest' && (
        <IngestPanel
          onDone={afterIngest}
          health={health}
          selectedSnapshot={filters.snapshot_id}
        />
      )}
      {tab === 'chat' && (
        <ChatPanel health={health} snapshotId={filters.snapshot_id} />
      )}
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

function IngestPanel({ onDone, health, selectedSnapshot }: {
  onDone: (snapshotId?: string) => void;
  health?: Health;
  selectedSnapshot?: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<IngestSummary | null>(null);
  const [stages, setStages] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
    setBusy('Parsing workbook…'); setError(null); setSummary(null); setStages({});
    try {
      const body = new FormData();
      body.append('file', file);
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
      const qs = selectedSnapshot
        ? `?snapshot_id=${encodeURIComponent(selectedSnapshot)}` : '';
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
          const f = e.dataTransfer.files?.[0];
          if (f) upload(f);
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
          Drop a QA workbook here, or click to choose
        </div>
        <div className="text-[11px] text-neutral-600 mt-0.5">
          .xlsx or .xlsm — sheets are identified by structure, not by name
        </div>
        <input
          ref={fileRef} type="file" accept=".xlsx,.xlsm" className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }}
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
          <Play size={13} /> Run analysis
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
