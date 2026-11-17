/**
 * Live agent run: the coordinator, its sub-agents, and every function tool they call.
 *
 * Built from `trace` events (agent/navigator/trace.py): one start + one end per tool call,
 * from every agent, as they happen. A call made by a sub-agent nests under the coordinator's
 * call to that sub-agent.
 */
import {useEffect, useState} from 'react';
import type {TraceEvent} from './api/client';

export type TraceNode = {
  id: string;
  agent: string;
  tool: string;
  kind: 'tool' | 'agent';
  label: string;
  args: Record<string, unknown>;
  summary: string;
  detail: string;
  ok: boolean;
  status: 'running' | 'done' | 'error';
  ms: number | null;
  startedAt: number;
  children: TraceNode[];
};

export type Run = {turn: number; nodes: TraceNode[]; startedAt: number; endedAt: number | null};

export const AGENTS: {id: string; name: string; role: string; tools: string[]}[] = [
  {id: 'navigator', name: 'Navigator', role: 'Coordinator', tools: ['analyze_photos', 'resolve_date', 'match_fund', 'submit_brief', 'add_equity_note']},
  {id: 'evidence_researcher', name: 'Evidence researcher', role: 'Sub-agent', tools: ['semantic_search', 'locate_block', 'tract_context']},
  {id: 'equity_auditor', name: 'Equity auditor', role: 'Sub-agent', tools: ['equity_audit']},
  {id: 'data_analyst', name: 'Data analyst', role: 'Sub-agent', tools: ['BigQuery MCP']},
];
const AGENT_NAME = Object.fromEntries(AGENTS.map(a => [a.id, a.name]));

/** What each tool is, in plain words (tooltip + subtitle). */
const TOOL_INFO: Record<string, string> = {
  analyze_photos: 'Gemini vision on tenant photos → structured hazards (not 311 evidence)',
  resolve_date: 'Date phrase → exact date (code, no LLM)',
  semantic_search: 'BigQuery AI.EMBED + VECTOR_SEARCH, then the decoy filter',
  locate_block: 'Block address → census tract',
  tract_context: 'ACS rent burden + modeled filings (4 quarters summed)',
  match_fund: 'Fund eligibility rules from the program bulletins',
  submit_brief: 'Builds the brief from real tool rows only',
  add_equity_note: 'Adds the post-brief equity note',
  equity_audit: 'Post-output audit_* comparison vs metro',
  execute_sql_readonly: 'Google-managed BigQuery MCP server',
  list_table_ids: 'Google-managed BigQuery MCP server',
  get_table_info: 'Google-managed BigQuery MCP server',
  evidence_researcher: 'Sub-agent: 311 evidence, statutes, tract',
  equity_auditor: 'Sub-agent: post-brief equity audit',
  data_analyst: 'Sub-agent: read-only BigQuery via MCP',
};

export function newRun(turn: number): Run {
  return {turn, nodes: [], startedAt: Date.now(), endedAt: null};
}

function walk(nodes: TraceNode[], f: (n: TraceNode) => void) {
  for (const n of nodes) {
    f(n);
    walk(n.children, f);
  }
}

/** Apply one trace event to a run (immutably). */
export function applyTrace(run: Run, ev: TraceEvent, now = Date.now()): Run {
  const nodes = structuredClone(run.nodes) as TraceNode[];
  let target: TraceNode | undefined;
  walk(nodes, n => {
    if (n.id === ev.id) target = n;
  });

  if (ev.phase === 'start' || !target) {
    if (!target) {
      target = {
        id: ev.id, agent: ev.agent, tool: ev.tool, kind: ev.kind, label: ev.label ?? '', args: ev.args ?? {},
        summary: '', detail: '', ok: true, status: 'running', ms: null, startedAt: now, children: [],
      };
      // A sub-agent's call nests under the coordinator's call to that sub-agent (latest one).
      let parent: TraceNode | undefined;
      if (ev.agent !== 'navigator') {
        walk(nodes, n => {
          if (n.kind === 'agent' && n.tool === ev.agent) parent = n;
        });
        if (!parent) {
          // No coordinator call seen (mock replay, or single-agent mode naming): synthesize one.
          parent = {
            id: `agent-${ev.agent}-${now}`, agent: 'navigator', tool: ev.agent, kind: 'agent', label: '', args: {},
            summary: '', detail: '', ok: true, status: 'running', ms: null, startedAt: now, children: [],
          };
          nodes.push(parent);
        }
      }
      (parent ? parent.children : nodes).push(target);
    }
  }
  if (ev.phase === 'end') {
    target.summary = ev.summary ?? '';
    target.detail = ev.detail ?? '';
    target.ok = ev.ok !== false;
    target.status = target.ok ? 'done' : 'error';
    target.ms = ev.ms ?? now - target.startedAt;
  }
  return {...run, nodes};
}

/** Close a run at turn end: anything still "running" (e.g. a synthesized parent) is done. */
export function finishRun(run: Run, now = Date.now()): Run {
  const nodes = structuredClone(run.nodes) as TraceNode[];
  walk(nodes, n => {
    if (n.status === 'running') {
      n.status = 'done';
      n.ms = n.ms ?? now - n.startedAt;
      if (n.kind === 'agent' && !n.summary) n.summary = `${n.children.length} tool call${n.children.length === 1 ? '' : 's'}`;
    }
  });
  return {...run, nodes, endedAt: run.endedAt ?? now};
}

export function activeAgents(run?: Run | null): {running: Set<string>; used: Set<string>} {
  const running = new Set<string>();
  const used = new Set<string>();
  if (!run) return {running, used};
  walk(run.nodes, n => {
    const who = n.kind === 'agent' ? n.tool : n.agent;
    used.add(n.agent);
    used.add(who);
    if (n.status === 'running') running.add(who);
  });
  if (run.endedAt === null && running.size === 0) running.add('navigator'); // thinking between calls
  return {running, used};
}

function fmt(ms: number | null): string {
  if (ms === null || ms === undefined) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function useTick(active: boolean) {
  const [, set] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => set(x => x + 1), 250);
    return () => window.clearInterval(t);
  }, [active]);
}

function StatusIcon({s}: {s: TraceNode['status']}) {
  if (s === 'running') return <span className="nv-ar-spin" aria-label="running" />;
  if (s === 'error')
    return (
      <span className="nv-ar-icon is-error" aria-label="error">
        ✕
      </span>
    );
  return (
    <span className="nv-ar-icon is-done" aria-label="done">
      ✓
    </span>
  );
}

function NodeRow({n, depth}: {n: TraceNode; depth: number}) {
  const [open, setOpen] = useState(false);
  const live = n.status === 'running' ? Date.now() - n.startedAt : n.ms;
  const isAgent = n.kind === 'agent';
  const owner = isAgent ? n.tool : n.agent;
  return (
    <li className={`nv-ar-node agent-${owner}${isAgent ? ' is-agent' : ''} is-${n.status}`}>
      <button type="button" className="nv-ar-row" onClick={() => setOpen(o => !o)} aria-expanded={open} title={TOOL_INFO[n.tool] ?? ''}>
        <StatusIcon s={n.status} />
        {isAgent ? (
          <span className="nv-ar-agent">
            <span className="nv-ar-dot" />
            {AGENT_NAME[n.tool] ?? n.tool}
            <span className="nv-ar-badge">sub-agent</span>
          </span>
        ) : (
          <span className="nv-ar-tool">{n.tool}()</span>
        )}
        {n.label ? <span className="nv-ar-label">{n.label}</span> : null}
        <span className="nv-ar-time">{fmt(live)}</span>
      </button>
      {n.summary ? (
        <div className={`nv-ar-result${n.ok ? '' : ' is-error'}`}>
          <span aria-hidden="true">↳</span> {n.summary}
        </div>
      ) : n.status === 'running' && !isAgent ? (
        <div className="nv-ar-result is-pending">{TOOL_INFO[n.tool] ?? 'working…'}</div>
      ) : null}
      {open && Object.keys(n.args).length ? <pre className="nv-ar-args"><b>input</b>{'\n'}{JSON.stringify(n.args, null, 2)}</pre> : null}
      {open && n.detail ? <pre className="nv-ar-args"><b>report to coordinator</b>{'\n'}{n.detail}</pre> : null}
      {n.children.length || (isAgent && n.status === 'running') ? (
        <ul className="nv-ar-children">
          {n.children.map(c => (
            <NodeRow key={c.id} n={c} depth={depth + 1} />
          ))}
          {isAgent && n.status === 'running' && n.children.every(c => c.status !== 'running') ? (
            <li className="nv-ar-result is-pending nv-ar-thinking">{n.children.length ? 'Gemini is reasoning over the results…' : 'Gemini is planning which tools to call…'}</li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}

export function AgentRunCard({run}: {run: Run}) {
  const running = run.endedAt === null;
  useTick(running);
  const [collapsed, setCollapsed] = useState(false);
  let calls = 0;
  const agents = new Set<string>(['navigator']);
  walk(run.nodes, n => {
    if (n.kind === 'tool') calls++;
    if (n.kind === 'agent') agents.add(n.tool);
  });
  const elapsed = (run.endedAt ?? Date.now()) - run.startedAt;
  return (
    <section className={`nv-ar${running ? ' is-running' : ''}`} aria-label="Agent run">
      <header className="nv-ar-head">
        <button type="button" className="nv-ar-toggle" onClick={() => setCollapsed(c => !c)} aria-expanded={!collapsed}>
          {collapsed ? '▸' : '▾'}
        </button>
        <span className="nv-ar-title">
          {running ? <span className="nv-ar-pulse" aria-hidden="true" /> : null}
          {running ? 'Agents working' : 'Agent run'}
        </span>
        <span className="nv-ar-meta">
          {agents.size} agent{agents.size === 1 ? '' : 's'} · {calls} tool call{calls === 1 ? '' : 's'} · {fmt(elapsed)}
        </span>
      </header>
      {collapsed ? null : (
        <ul className="nv-ar-tree">
          <li className="nv-ar-node agent-navigator is-agent is-root">
            <div className="nv-ar-row is-static">
              {running ? <span className="nv-ar-spin" /> : <span className="nv-ar-icon is-done">✓</span>}
              <span className="nv-ar-agent">
                <span className="nv-ar-dot" />
                Navigator
                <span className="nv-ar-badge">coordinator · Gemini</span>
              </span>
            </div>
            <ul className="nv-ar-children">
              {run.nodes.map(n => (
                <NodeRow key={n.id} n={n} depth={1} />
              ))}
              {running && !run.nodes.some(n => n.status === 'running') ? (
                <li className="nv-ar-result is-pending nv-ar-thinking">{run.nodes.length ? 'Navigator is reasoning over the results…' : 'Navigator is planning the next step…'}</li>
              ) : null}
            </ul>
          </li>
        </ul>
      )}
    </section>
  );
}

/** Header strip: the agent team, lit up while each agent works. */
export function AgentTeam({run}: {run?: Run | null}) {
  useTick(!!run && run.endedAt === null);
  const {running, used} = activeAgents(run);
  return (
    <div className="nv-team" aria-label="Agent team">
      {AGENTS.map((a, i) => (
        <div key={a.id} className={`nv-team-agent agent-${a.id}${running.has(a.id) ? ' is-running' : used.has(a.id) ? ' is-used' : ''}`} title={`${a.role}: ${a.tools.join(', ')}`}>
          {i > 0 ? <span className="nv-team-link" aria-hidden="true" /> : null}
          <span className="nv-ar-dot" />
          <span className="nv-team-name">{a.name}</span>
          <span className="nv-team-role">{running.has(a.id) ? 'working…' : a.role}</span>
        </div>
      ))}
    </div>
  );
}
