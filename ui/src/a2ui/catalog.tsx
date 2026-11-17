/**
 * The navigator's A2UI v1.0 catalog: the A2UI basic catalog plus domain components.
 *
 * The server (api/a2ui/surfaces.py) composes surfaces from these names. Each component here
 * has an API (name + Zod schema, which is what the A2UI MessageProcessor validates against)
 * and a React implementation. `npm run catalog:export` writes the JSON definition to
 * api/a2ui/navigator_catalog.json so agents and validators can read it.
 *
 * Trust rules from the design spec live in these components:
 *   - status is never color alone: every tone has a text label;
 *   - blue = kept evidence, orange = excluded, violet = modeled, red = deadline, green = eligible;
 *   - excluded records always show the failing field.
 */
import {useEffect, useRef, useState, type ComponentType} from 'react';
import {motion} from 'motion/react';
import {
  ArrowLeft, CheckCircle2, Copy, Download, ExternalLink, FileText, Image as ImageIcon, MapPin, Mic, Printer,
  RefreshCw, Send, Sparkles, UserPlus, Users, type LucideProps,
} from 'lucide-react';
import {MapView as MapViewImpl} from './MapView';
import {z} from 'zod';
import {CommonSchemas} from '@a2ui/web_core/v1_0';
import {basicCatalog} from '@a2ui/web_core/catalogs/basic/v1';
import {createComponentImplementation} from '@a2ui/react';
import {toHtml} from './markdown';

export const NAVIGATOR_CATALOG_ID = 'https://a4i-housing-navigator.dev/a2ui/v1/navigator_catalog.json';

const S = CommonSchemas;
const Tone = z.enum(['evidence', 'excluded', 'deadline', 'eligible', 'modeled', 'neutral']);
const DynTone = z.union([Tone, S.DynamicString]);
type ChildRef = string | {id: string; basePath?: string};

/** Icons the server may name (IconButton.icon, SectionTitle.icon). */
export const ICONS: Record<string, ComponentType<LucideProps>> = {
  userPlus: UserPlus, users: Users, sparkles: Sparkles, copy: Copy, download: Download, refresh: RefreshCw,
  checkCircle: CheckCircle2, fileText: FileText, printer: Printer, arrowLeft: ArrowLeft, mapPin: MapPin,
  mic: Mic, image: ImageIcon, send: Send, externalLink: ExternalLink,
};
const IconName = z.enum(Object.keys(ICONS) as [string, ...string[]]);
const Ico = ({name, size = 16}: {name?: string; size?: number}) => {
  const C = name ? ICONS[name] : undefined;
  return C ? <C size={size} strokeWidth={2} aria-hidden="true" /> : null;
};

/** Cards fade and rise in as the agent adds them. */
const enter = {initial: {opacity: 0, y: 8}, animate: {opacity: 1, y: 0}, transition: {duration: 0.28, ease: 'easeOut' as const}};

const tone = (t: unknown) => `nv-tone-${typeof t === 'string' && t ? t : 'neutral'}`;
const kids = (list: ChildRef[] | undefined, build: (id: string, base?: string) => React.ReactNode) =>
  (list ?? []).map((c, i) =>
    typeof c === 'string' ? <div key={c}>{build(c)}</div> : <div key={`${c.id}:${c.basePath ?? i}`}>{build(c.id, c.basePath)}</div>,
  );
/** Scrolls a card into view when the agent (or a citation chip) focuses it. */
function useFocusScroll<T extends HTMLElement>(focused?: boolean) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }, [focused]);
  return ref;
}

const Html = ({text, className, inline}: {text?: string; className?: string; inline?: boolean}) =>
  text ? <div className={className} dangerouslySetInnerHTML={{__html: toHtml(text, {inline, chips: true})}} /> : null;

// ------------------------------------------------------------------ small parts

export const Badge = createComponentImplementation(
  {name: 'Badge', schema: z.object({text: S.DynamicString, tone: DynTone.optional()}).describe('A short status label with a tone.')},
  ({props}) => (props.text ? <span className={`nv-badge ${tone(props.tone)}`}>{props.text}</span> : null),
);

export const SectionTitle = createComponentImplementation(
  {
    name: 'SectionTitle',
    schema: z
      .object({text: S.DynamicString, meta: S.DynamicString.optional(), icon: IconName.optional()})
      .describe('A panel or section heading with an optional icon and right-aligned metadata.'),
  },
  ({props}) => (
    <div className="nv-section-title">
      <h2>
        <Ico name={props.icon} />
        {props.text}
      </h2>
      {props.meta ? <span>{props.meta}</span> : null}
    </div>
  ),
);

export const Callout = createComponentImplementation(
  {
    name: 'Callout',
    schema: z
      .object({title: S.DynamicString.optional(), text: S.DynamicString, tone: DynTone.optional()})
      .describe('A tinted note. Renders nothing when text is empty, so it doubles as an empty state. Text is Markdown.'),
  },
  ({props}) =>
    props.text ? (
      <div className={`nv-callout ${tone(props.tone)}`}>
        {props.title ? <strong className="nv-callout-title">{props.title}</strong> : null}
        <Html text={props.text} />
      </div>
    ) : null,
);

export const Wrap = createComponentImplementation(
  {
    name: 'Wrap',
    schema: z
      .object({children: S.ChildList, justify: z.enum(['start', 'spaceBetween', 'end']).optional()})
      .describe('A row of children that wraps onto new lines on narrow screens.'),
  },
  ({props, buildChild}) => (
    <div className={`nv-wrap nv-justify-${props.justify ?? 'start'}`}>{kids(props.children as ChildRef[], buildChild)}</div>
  ),
);

export const Grid = createComponentImplementation(
  {
    name: 'Grid',
    schema: z.object({columns: z.number().int().min(1).max(4).optional(), children: S.ChildList}).describe('An equal-width grid that collapses to one column on narrow screens.'),
  },
  ({props, buildChild}) => (
    <div className="nv-grid" style={{['--nv-cols' as string]: String(props.columns ?? 2)}}>
      {kids(props.children as ChildRef[], buildChild)}
    </div>
  ),
);

export const Collapsible = createComponentImplementation(
  {
    name: 'Collapsible',
    schema: z.object({title: S.DynamicString, tone: DynTone.optional(), open: S.DynamicBoolean.optional(), child: S.ComponentId}).describe('A disclosure button that shows or hides one child.'),
  },
  ({props, buildChild}) => {
    const [open, setOpen] = useState<boolean>(props.open ?? false);
    useEffect(() => {
      setOpen(props.open ?? false);
    }, [props.open]);
    // The child stays mounted and is only hidden (see PanelTabs): no title hides the whole box.
    return (
      <div className="nv-collapsible" hidden={!props.title}>
        <button type="button" className={`nv-collapsible-head ${tone(props.tone)}`} aria-expanded={open} onClick={() => setOpen(!open)}>
          <span>{props.title}</span>
          <span>{open ? 'Hide' : 'Show'}</span>
        </button>
        <div className="nv-collapsible-body" hidden={!open}>
          {buildChild(props.child)}
        </div>
      </div>
    );
  },
);

export const PanelTabs = createComponentImplementation(
  {
    name: 'PanelTabs',
    schema: z
      .object({
        tabs: z.array(z.object({key: z.string(), title: S.DynamicString, child: S.ComponentId})),
        active: S.DynamicString.optional(),
        focusSeq: S.DynamicNumber.optional(),
      })
      .describe('Tabs whose selected tab the agent can set through `active` (bump `focusSeq` to re-select).'),
  },
  ({props, buildChild}) => {
    const first = props.tabs[0]?.key ?? '';
    const [current, setCurrent] = useState(props.active || first);
    useEffect(() => {
      setCurrent(props.active || first);
    }, [props.active, props.focusSeq, first]);
    const tab = props.tabs.find(t => t.key === current) ?? props.tabs[0];
    return (
      <div className="nv-tabs">
        <div role="tablist" aria-label="Case documents" className="nv-tablist">
          {props.tabs.map(t => (
            <button key={t.key} type="button" role="tab" aria-selected={t.key === tab?.key} className="nv-tab" onClick={() => setCurrent(t.key)}>
              {t.title}
            </button>
          ))}
        </div>
        {/* Every panel stays mounted and inactive ones are hidden: unmounting a panel while the
            server updates its data races the web components' update cycle. */}
        {props.tabs.map(t => (
          <div key={t.key} role="tabpanel" className="nv-tabpanel" hidden={t.key !== tab?.key}>
            {buildChild(t.child)}
          </div>
        ))}
      </div>
    );
  },
);

// ------------------------------------------------------------------ case header & queue

export const CaseHeader = createComponentImplementation(
  {
    name: 'CaseHeader',
    schema: z.object({eyebrow: S.DynamicString, title: S.DynamicString, subtitle: S.DynamicString.optional()}).describe('Case id line, case title and the block/tract line.'),
  },
  ({props}) => (
    <div className="nv-case-header">
      <div className="nv-mono nv-muted">{props.eyebrow}</div>
      <h1>{props.title}</h1>
      {props.subtitle ? <div className="nv-sub">{props.subtitle}</div> : null}
    </div>
  ),
);

export const DeadlineCard = createComponentImplementation(
  {
    name: 'DeadlineCard',
    schema: z.object({label: S.DynamicString, value: S.DynamicString, detail: S.DynamicString.optional(), tone: DynTone.optional()}).describe('Hearing countdown block, top right of every case.'),
  },
  ({props}) => (
    <div className={`nv-deadline ${tone(props.tone)}`}>
      <div className="nv-deadline-label">{props.label}</div>
      <div className="nv-deadline-value">{props.value}</div>
      {props.detail ? <div className="nv-deadline-detail">{props.detail}</div> : null}
    </div>
  ),
);

type Stage = {n?: number; key?: string; label: string; state: string; detail?: string; note?: string};

export const StepTracker = createComponentImplementation(
  {
    name: 'StepTracker',
    schema: z.object({steps: S.DynamicValue}).describe('Case progress. `steps` binds to a list of {label, state: done|current|todo}.'),
  },
  ({props}) => {
    const steps = (Array.isArray(props.steps) ? props.steps : []) as Stage[];
    const done = steps.filter(s => s.state === 'done' || s.state === 'skipped').length;
    return (
      <div className="nv-stages-wrap">
        <div className="nv-stages-head">
          <span>Case progress</span>
          <span className="nv-stages-count">
            {done}/{steps.length} stages
          </span>
          <span className="nv-stages-bar" aria-hidden="true">
            <span style={{width: `${steps.length ? (done / steps.length) * 100 : 0}%`}} />
          </span>
        </div>
        <ol className="nv-stages" aria-label="Case progress">
          {steps.map((s, i) => (
            <motion.li
              key={s.key ?? s.label}
              initial={{opacity: 0, y: 4}}
              animate={{opacity: 1, y: 0}}
              transition={{delay: i * 0.03}}
              className={`nv-stage is-${s.state}`}
              aria-current={s.state === 'current' ? 'step' : undefined}
              title={s.note || s.detail || s.label}
            >
              <span className="nv-stage-num" aria-hidden="true">
                {s.state === 'done' ? '✓' : s.state === 'warn' ? '!' : s.state === 'skipped' ? '–' : s.n ?? i + 1}
              </span>
              <span className="nv-stage-text">
                <span className="nv-stage-label">{s.label}</span>
                {s.detail ? <span className="nv-stage-detail">{s.detail}</span> : null}
                {s.note ? <span className="nv-stage-note">{s.note}</span> : null}
              </span>
            </motion.li>
          ))}
        </ol>
      </div>
    );
  },
);

export const QueueItem = createComponentImplementation(
  {
    name: 'QueueItem',
    schema: z
      .object({
        caseId: S.DynamicString,
        badge: S.DynamicString.optional(),
        badgeTone: DynTone.optional(),
        title: S.DynamicString,
        subtitle: S.DynamicString.optional(),
        status: S.DynamicString.optional(),
        statusTone: DynTone.optional(),
        selected: S.DynamicBoolean.optional(),
        action: S.Action,
      })
      .describe('One intake in the queue. Selecting it dispatches `action` (open_case).'),
  },
  ({props}) => (
    <motion.button layout {...enter} type="button" className={`nv-queue-item${props.selected ? ' is-selected' : ''}`} aria-current={props.selected ? 'true' : undefined} onClick={() => props.action?.()}>
      <span className="nv-row-between">
        <span className="nv-mono nv-small">{props.caseId}</span>
        {props.badge ? <span className={`nv-badge ${tone(props.badgeTone)}`}>{props.badge}</span> : null}
      </span>
      <span className="nv-queue-title">{props.title}</span>
      <span className="nv-small nv-muted">{props.subtitle}</span>
      {props.status ? <span className={`nv-small nv-status ${tone(props.statusTone)}`}>{props.status}</span> : null}
    </motion.button>
  ),
);

// ------------------------------------------------------------------ evidence

export const SimilarityBar = createComponentImplementation(
  {
    name: 'SimilarityBar',
    schema: z.object({value: S.DynamicNumber, weak: S.DynamicBoolean.optional()}).describe('Cosine similarity, 0–1, as a bar with the number.'),
  },
  ({props}) => <Similarity value={props.value} weak={props.weak} />,
);

function Similarity({value, weak}: {value?: number; weak?: boolean}) {
  const v = Math.max(0, Math.min(1, Number(value ?? 0)));
  return (
    <div className="nv-sim">
      <span className="nv-sim-label">Similarity</span>
      <div className="nv-sim-track" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={v} aria-label="Similarity">
        <div className={`nv-sim-fill${weak ? ' is-weak' : ''}`} style={{width: `${v * 100}%`}} />
      </div>
      <span className="nv-mono nv-small">{v.toFixed(2)}</span>
    </div>
  );
}

export const RecordCard = createComponentImplementation(
  {
    name: 'RecordCard',
    schema: z
      .object({
        recordId: S.DynamicString,
        badge: S.DynamicString.optional(),
        badgeTone: DynTone.optional(),
        title: S.DynamicString,
        meta: S.DynamicString.optional(),
        quote: S.DynamicString.optional(),
        similarity: S.DynamicNumber.optional(),
        weak: S.DynamicBoolean.optional(),
        focused: S.DynamicBoolean.optional(),
        updated: S.DynamicBoolean.optional(),
      })
      .describe('A corroborating 311 record kept after the decoy filter.'),
  },
  ({props}) => <RecordCardView {...props} />,
);

function RecordCardView(props: {recordId?: string; badge?: string; badgeTone?: unknown; title?: string; meta?: string; quote?: string; similarity?: number; weak?: boolean; focused?: boolean; updated?: boolean}) {
  const ref = useFocusScroll<HTMLElement>(props.focused);
  return (
    <motion.article {...enter} ref={ref} id={`rec-${props.recordId}`} className={`nv-card${props.focused ? ' is-focused' : ''}`}>
      <div className="nv-row-between">
        <span className="nv-mono nv-small nv-strong">{props.recordId}</span>
        <span className="nv-row-gap">
          {props.updated ? <span className="nv-badge nv-tone-eligible">Updated</span> : null}
          {props.badge ? <span className={`nv-badge ${tone(props.badgeTone)}`}>{props.badge}</span> : null}
        </span>
      </div>
      <div className="nv-card-title">{props.title}</div>
      {props.meta ? <div className="nv-small nv-muted">{props.meta}</div> : null}
      {props.quote ? <p className="nv-quote">{props.quote}</p> : null}
      {props.similarity != null ? <Similarity value={props.similarity} weak={props.weak} /> : null}
      <div className="nv-provenance">public record</div>
    </motion.article>
  );
}

export const ExcludedCard = createComponentImplementation(
  {
    name: 'ExcludedCard',
    schema: z
      .object({
        heading: S.DynamicString,
        label: S.DynamicString,
        summary: S.DynamicString.optional(),
        detail: S.DynamicString,
        focused: S.DynamicBoolean.optional(),
        actionLabel: S.DynamicString.optional(),
        action: S.Action.optional(),
      })
      .describe('A vector-search hit the filter threw out, with the failing field = value.'),
  },
  ({props}) => <ExcludedCardView {...props} />,
);

function ExcludedCardView(props: {heading?: string; label?: string; summary?: string; detail?: string; focused?: boolean; actionLabel?: string; action?: () => unknown}) {
  const ref = useFocusScroll<HTMLDivElement>(props.focused);
  return (
    <motion.div {...enter} ref={ref} className={`nv-excluded${props.focused ? ' is-focused' : ''}`}>
      <div className="nv-row-between">
        <span className="nv-mono nv-small">{props.heading}</span>
        <span className="nv-excluded-label">{props.label}</span>
      </div>
      {props.summary ? <p className="nv-small">{props.summary}</p> : null}
      <p className="nv-small nv-strong">{props.detail}</p>
      {props.action ? (
        <button type="button" className="nv-link-button" onClick={() => props.action?.()}>
          {props.actionLabel ?? 'Ask why'}
        </button>
      ) : null}
    </motion.div>
  );
}

// ------------------------------------------------------------------ law, funds, tract

export const StatuteCard = createComponentImplementation(
  {
    name: 'StatuteCard',
    schema: z
      .object({
        citation: S.DynamicString,
        statuteId: S.DynamicString.optional(),
        title: S.DynamicString,
        protection: S.DynamicString.optional(),
        appliesBecause: S.DynamicString.optional(),
        needs: S.DynamicString.optional(),
        primary: S.DynamicBoolean.optional(),
        updated: S.DynamicBoolean.optional(),
        compact: z.boolean().optional(),
      })
      .describe('A matched statute: citation, protection, and what the tenant still needs for it to apply.'),
  },
  ({props}) => (
    <motion.article {...enter} className={`nv-card${props.primary ? ' is-primary' : ''}${props.compact ? ' is-compact' : ''}`}>
      <div className="nv-row-between">
        <span className="nv-mono nv-small nv-citation">
          {props.citation}
          {props.statuteId ? ` · ${props.statuteId}` : ''}
        </span>
        {props.updated ? <span className="nv-badge nv-tone-eligible">Updated</span> : null}
      </div>
      <div className="nv-card-title">{props.title}</div>
      {props.protection ? <p className="nv-small">{props.protection}</p> : null}
      {props.appliesBecause ? <p className="nv-small">Applies because: {props.appliesBecause}</p> : null}
      {props.needs ? <div className="nv-needs">{props.needs}</div> : null}
    </motion.article>
  ),
);

export const FundCard = createComponentImplementation(
  {
    name: 'FundCard',
    schema: z
      .object({
        name: S.DynamicString,
        agency: S.DynamicString.optional(),
        fitLabel: S.DynamicString,
        fitTone: DynTone.optional(),
        why: S.DynamicString.optional(),
        checklist: S.DynamicString.optional(),
        intakeLabel: S.DynamicString.optional(),
        action: S.Action.optional(),
      })
      .describe('An emergency fund with its fit (Likely / Conditional / Needs info) and why. `action` opens the intake page.'),
  },
  ({props}) => (
    <motion.article {...enter} className="nv-card">
      <div className="nv-row-between">
        <strong>{props.name}</strong>
        <span className={`nv-badge ${tone(props.fitTone)}`}>{props.fitLabel}</span>
      </div>
      {props.agency ? <div className="nv-small nv-muted">{props.agency}</div> : null}
      {props.checklist ? <div className="nv-small nv-checklist">{props.checklist}</div> : null}
      {props.why ? <p className="nv-small">{props.why}</p> : null}
      {props.intakeLabel && props.action ? (
        <button type="button" className="nv-link-button" onClick={() => props.action?.()}>
          <ExternalLink size={13} aria-hidden="true" /> Intake: {props.intakeLabel}
        </button>
      ) : null}
    </motion.article>
  ),
);

export const StatTile = createComponentImplementation(
  {
    name: 'StatTile',
    schema: z
      .object({label: S.DynamicString, value: S.DynamicString, note: S.DynamicString.optional(), modeled: S.DynamicBoolean.optional()})
      .describe('A single figure. `modeled` adds the violet "modeled" tag; otherwise it reads "public record".'),
  },
  ({props}) => (
    <motion.div {...enter} className="nv-stat">
      <div className="nv-small nv-muted">{props.label}</div>
      <div className="nv-stat-value">{props.value}</div>
      <div className="nv-small nv-muted">
        {props.note}
        {props.note ? ' · ' : ''}
        {props.modeled ? <span className="nv-modeled">modeled</span> : <span>public record</span>}
      </div>
    </motion.div>
  ),
);

// ------------------------------------------------------------------ memo & brief

export const MemoView = createComponentImplementation(
  {
    name: 'MemoView',
    schema: z
      .object({markdown: S.DynamicString, statusLabel: S.DynamicString.optional(), statusTone: DynTone.optional(), variant: z.enum(['card', 'quote']).optional()})
      .describe('The legal-aid intake memo, rendered from Markdown.'),
  },
  ({props}) => (
    <div className={`nv-memo nv-memo-${props.variant ?? 'card'}`}>
      {props.statusLabel ? <span className={`nv-badge ${tone(props.statusTone)}`}>{props.statusLabel}</span> : null}
      <Html text={props.markdown} className="nv-prose" />
    </div>
  ),
);

export const DocHeader = createComponentImplementation(
  {
    name: 'DocHeader',
    schema: z
      .object({
        eyebrow: S.DynamicString,
        title: S.DynamicString,
        subtitle: S.DynamicString.optional(),
        rightLabel: S.DynamicString.optional(),
        rightValue: S.DynamicString.optional(),
        rightNote: S.DynamicString.optional(),
      })
      .describe('Printed document header with the hearing on the right.'),
  },
  ({props}) => (
    <header className="nv-doc-header">
      <div>
        <div className="nv-mono nv-small nv-muted">{props.eyebrow}</div>
        <h1>{props.title}</h1>
        <div className="nv-sub">{props.subtitle}</div>
      </div>
      <div className="nv-doc-right">
        <div className="nv-deadline-label">{props.rightLabel}</div>
        <div className="nv-deadline-value">{props.rightValue}</div>
        <div className="nv-small nv-muted">{props.rightNote}</div>
      </div>
    </header>
  ),
);

export const DataTable = createComponentImplementation(
  {
    name: 'DataTable',
    schema: z
      .object({columns: S.DynamicStringList.optional(), rows: S.DynamicValue, monoFirstColumn: z.boolean().optional()})
      .describe('A read-only table. `rows` binds to a list of string lists.'),
  },
  ({props}) => {
    const rows = (Array.isArray(props.rows) ? props.rows : []) as unknown[][];
    const cols = (props.columns ?? []) as string[];
    if (!rows.length) return <p className="nv-small nv-muted">Nothing yet.</p>;
    return (
      <div className="nv-table-wrap">
        <table className="nv-table">
          {cols.length ? (
            <thead>
              <tr>{cols.map(c => <th key={c}>{c}</th>)}</tr>
            </thead>
          ) : null}
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((cell, j) => (
                  <td key={j} className={j === 0 && props.monoFirstColumn ? 'nv-mono' : undefined}>
                    {String(cell ?? '')
                      .split('\n')
                      .map((line, k) => (k === 0 ? <span key={k}>{line}</span> : <span key={k} className="nv-cell-sub">{line}</span>))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  },
);

// ------------------------------------------------------------------ buttons, photos, map

export const IconButton = createComponentImplementation(
  {
    name: 'IconButton',
    schema: z
      .object({
        icon: IconName,
        label: S.DynamicString,
        variant: z.enum(['default', 'primary', 'chip']).optional(),
        action: S.Action,
        enabled: S.DynamicBoolean.optional(),
        block: z.boolean().optional(),
      })
      .describe('A button with a leading icon. `enabled` false disables it; `block` makes it full width.'),
  },
  ({props}) => (
    <motion.button
      type="button"
      whileHover={props.enabled === false ? undefined : {y: -1}}
      whileTap={props.enabled === false ? undefined : {scale: 0.97}}
      className={`nv-btn nv-btn-${props.variant ?? 'default'}${props.block ? ' is-block' : ''}`}
      disabled={props.enabled === false}
      onClick={() => props.action?.()}
    >
      <Ico name={props.icon} />
      <span>{props.label}</span>
    </motion.button>
  ),
);

type Hazard = {type?: string; severity?: string; where?: string; confidence?: number; visible_evidence?: string};
type Photo = {url: string; name?: string; caption?: string; hazards?: Hazard[]; analyzed?: boolean; people_visible?: boolean};

const SEV_RANK: Record<string, number> = {low: 0, moderate: 1, severe: 2};
const hazardLabel = (t?: string) => (t ?? 'other').replace(/_/g, ' ');
const worstHazard = (hs: Hazard[] = []) =>
  hs.reduce<Hazard | null>((w, h) => (!w || (SEV_RANK[h.severity ?? 'low'] ?? 0) > (SEV_RANK[w.severity ?? 'low'] ?? 0) ? h : w), null);

function HazardChips({hazards}: {hazards: Hazard[]}) {
  return (
    <div className="nv-hazards">
      {hazards.map((h, i) => (
        <span key={i} className={`nv-hazard sev-${h.severity ?? 'low'}`} title={[h.where, h.visible_evidence].filter(Boolean).join(' · ')}>
          {hazardLabel(h.type)} · {h.severity}
        </span>
      ))}
    </div>
  );
}

export const PhotoGallery = createComponentImplementation(
  {
    name: 'PhotoGallery',
    schema: z
      .object({title: S.DynamicString, note: S.DynamicString.optional(), photos: S.DynamicValue})
      .describe('Tenant-provided photos (not a public record). Hidden when `title` is empty.'),
  },
  ({props}) => {
    const photos = (Array.isArray(props.photos) ? props.photos : []) as Photo[];
    const [open, setOpen] = useState<Photo | null>(null);
    if (!props.title) return null;
    return (
      <section className="nv-photos" aria-label={props.title}>
        <div className="nv-section-title">
          <h2>
            <ImageIcon size={16} aria-hidden="true" />
            {props.title}
          </h2>
          <span className="nv-badge nv-tone-neutral">tenant-provided · not 311 evidence</span>
        </div>
        <div className="nv-photo-cards">
          {photos.map((p, i) => {
            const worst = worstHazard(p.hazards);
            return (
              <motion.figure {...enter} transition={{...enter.transition, delay: i * 0.05}} key={p.url} className="nv-photo-card">
                <button type="button" className="nv-photo" onClick={() => setOpen(p)} aria-label={`Open photo ${p.name ?? i + 1}`}>
                  <img src={p.url} alt={p.caption || `Tenant photo ${i + 1}`} loading="lazy" />
                  {worst ? <span className={`nv-photo-flag sev-${worst.severity ?? 'low'}`}>{hazardLabel(worst.type)}</span> : null}
                </button>
                <figcaption>
                  {p.analyzed ? (
                    <>
                      {p.caption ? <p className="nv-photo-caption">{p.caption}</p> : null}
                      {p.hazards?.length ? <HazardChips hazards={p.hazards} /> : <span className="nv-small nv-muted">No visible hazard found.</span>}
                      {p.people_visible ? <span className="nv-hazard sev-moderate">people / personal info visible: redact</span> : null}
                    </>
                  ) : (
                    <span className="nv-small nv-muted">Not analyzed yet. Ask the navigator about this photo.</span>
                  )}
                </figcaption>
              </motion.figure>
            );
          })}
        </div>
        {props.note ? <p className="nv-small nv-muted">{props.note}</p> : null}
        {open ? (
          <div className="nv-lightbox" role="dialog" aria-modal="true" aria-label="Photo" onClick={() => setOpen(null)}>
            <motion.div className="nv-lightbox-body" initial={{scale: 0.94, opacity: 0}} animate={{scale: 1, opacity: 1}}>
              <img src={open.url} alt={open.caption || 'Tenant photo, enlarged'} />
              {open.analyzed ? (
                <div className="nv-lightbox-findings">
                  <strong>Gemini vision · tenant-provided photo</strong>
                  {open.caption ? <p>{open.caption}</p> : null}
                  <ul>
                    {(open.hazards ?? []).map((h, i) => (
                      <li key={i}>
                        <span className={`nv-hazard sev-${h.severity ?? 'low'}`}>
                          {hazardLabel(h.type)} · {h.severity}
                        </span>{' '}
                        {h.where}
                        {h.visible_evidence ? <em> {h.visible_evidence}</em> : null}
                        {typeof h.confidence === 'number' ? <span className="nv-muted"> ({Math.round(h.confidence * 100)}% confidence)</span> : null}
                      </li>
                    ))}
                  </ul>
                  <p className="nv-small">Not a public record or inspection finding. It cannot show when or where the photo was taken.</p>
                </div>
              ) : null}
            </motion.div>
          </div>
        ) : null}
      </section>
    );
  },
);

export const MapView = createComponentImplementation(
  {
    name: 'MapView',
    schema: z
      .object({
        address: S.DynamicString,
        center: S.DynamicValue.optional(),
        markers: S.DynamicValue.optional(),
        apiKey: S.DynamicString.optional(),
        openUrl: S.DynamicString.optional(),
      })
      .describe('Google Map of the tenant block. With `apiKey`: Maps JavaScript API with pins for `markers` [{id, label, lat, lng, kind}]; without: a Google Maps embed of `address`.'),
  },
  ({props}) => <MapViewImpl {...props} />,
);

// ------------------------------------------------------------------ the catalog

export const NAVIGATOR_COMPONENTS = [
  Badge, SectionTitle, Callout, Wrap, Grid, Collapsible, PanelTabs, CaseHeader, DeadlineCard, StepTracker,
  QueueItem, SimilarityBar, RecordCard, ExcludedCard, StatuteCard, FundCard, StatTile, MemoView, DocHeader, DataTable,
  IconButton, PhotoGallery, MapView,
];

/** Basic catalog (v1.0) + navigator components, under the navigator's own catalog id. */
export const navigatorCatalog = basicCatalog.derive({
  catalogId: NAVIGATOR_CATALOG_ID,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  components: [...basicCatalog.components.keys(), ...(NAVIGATOR_COMPONENTS as any[])],
});
