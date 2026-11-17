/**
 * Drag-and-drop workspace. Every section (queue, map, case header, conversation, documents) has a grip
 * in its title bar: drag it up or down, or into another column. The layout is saved in this browser.
 * Keyboard: focus a grip, press Space, move with the arrow keys, Space again to drop, Escape to cancel.
 */
import {useCallback, useState, type ReactNode} from 'react';
import {
  DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCorners, useDroppable, useSensor, useSensors,
  type DragEndEvent, type DragOverEvent, type DragStartEvent,
} from '@dnd-kit/core';
import {SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy} from '@dnd-kit/sortable';
import {CSS} from '@dnd-kit/utilities';
import {motion} from 'motion/react';
import {GripVertical, type LucideIcon} from 'lucide-react';

export type ColumnId = 'left' | 'center' | 'right';
export type Layout = Record<ColumnId, string[]>;
export type SectionDef = {title: string; icon: LucideIcon; actions?: ReactNode; body: ReactNode; className?: string};

export const DEFAULT_LAYOUT: Layout = {left: ['queue', 'map'], center: ['header', 'chat'], right: ['docs']};
const KEY = 'a4i.layout.v1';
const COLUMNS: ColumnId[] = ['left', 'center', 'right'];

export function loadLayout(): Layout {
  try {
    const saved = JSON.parse(window.localStorage.getItem(KEY) ?? 'null') as Layout | null;
    const all = Object.values(DEFAULT_LAYOUT).flat().sort().join();
    if (saved && COLUMNS.every(c => Array.isArray(saved[c])) && Object.values(saved).flat().sort().join() === all) return saved;
  } catch {
    /* storage blocked or bad JSON */
  }
  return DEFAULT_LAYOUT;
}

function saveLayout(l: Layout) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(l));
  } catch {
    /* storage blocked: the layout lasts for this visit */
  }
}

function Column({id, children}: {id: ColumnId; children: ReactNode}) {
  const {setNodeRef, isOver} = useDroppable({id});
  return (
    <div ref={setNodeRef} className={`nv-col nv-col-${id}${isOver ? ' is-over' : ''}`} data-column={id}>
      {children}
    </div>
  );
}

function Section({id, def}: {id: string; def: SectionDef}) {
  const {attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging} = useSortable({id});
  const Icon = def.icon;
  return (
    <motion.section
      ref={setNodeRef}
      layout="position"
      initial={{opacity: 0, y: 12}}
      animate={{opacity: isDragging ? 0.35 : 1, y: 0}}
      transition={{duration: 0.3, ease: 'easeOut'}}
      style={{transform: CSS.Transform.toString(transform), transition}}
      className={`nv-panel nv-section ${def.className ?? ''}${isDragging ? ' is-dragging' : ''}`}
      aria-label={def.title}
      data-section={id}
    >
      <header className="nv-section-bar">
        <button
          ref={setActivatorNodeRef}
          type="button"
          className="nv-grip"
          aria-label={`Move ${def.title} section`}
          title="Drag to move this section"
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} />
        </button>
        <Icon size={16} aria-hidden="true" className="nv-section-icon" />
        <h2>{def.title}</h2>
        <span className="nv-spacer" />
        {def.actions}
      </header>
      <div className="nv-section-body">{def.body}</div>
    </motion.section>
  );
}

export function Board({sections, layout, setLayout}: {sections: Record<string, SectionDef>; layout: Layout; setLayout: (l: Layout) => void}) {
  const [active, setActive] = useState<string | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, {activationConstraint: {distance: 6}}),
    useSensor(KeyboardSensor, {coordinateGetter: sortableKeyboardCoordinates}),
  );
  const columnOf = useCallback(
    (id: string): ColumnId | undefined => (COLUMNS.includes(id as ColumnId) ? (id as ColumnId) : COLUMNS.find(c => layout[c].includes(id))),
    [layout],
  );
  const update = (l: Layout) => {
    setLayout(l);
    saveLayout(l);
  };

  const onStart = (e: DragStartEvent) => setActive(String(e.active.id));
  const onOver = ({active: a, over}: DragOverEvent) => {
    if (!over) return;
    const from = columnOf(String(a.id));
    const to = columnOf(String(over.id));
    if (!from || !to || from === to) return;
    const target = layout[to];
    const idx = target.indexOf(String(over.id));
    update({
      ...layout,
      [from]: layout[from].filter(x => x !== a.id),
      [to]: [...target.slice(0, idx < 0 ? target.length : idx), String(a.id), ...target.slice(idx < 0 ? target.length : idx)],
    });
  };
  const onEnd = ({active: a, over}: DragEndEvent) => {
    setActive(null);
    if (!over) return;
    const col = columnOf(String(a.id));
    if (!col || col !== columnOf(String(over.id))) return;
    const items = layout[col];
    const from = items.indexOf(String(a.id));
    const to = items.indexOf(String(over.id));
    if (from >= 0 && to >= 0 && from !== to) update({...layout, [col]: arrayMove(items, from, to)});
  };

  const activeDef = active ? sections[active] : null;
  return (
    <DndContext sensors={sensors} collisionDetection={closestCorners} onDragStart={onStart} onDragOver={onOver} onDragEnd={onEnd} onDragCancel={() => setActive(null)}>
      <div className="nv-board">
        {COLUMNS.map(c => (
          <SortableContext key={c} id={c} items={layout[c]} strategy={verticalListSortingStrategy}>
            <Column id={c}>
              {layout[c].map(id => (sections[id] ? <Section key={id} id={id} def={sections[id]} /> : null))}
              {layout[c].length === 0 ? <div className="nv-col-empty">Drop a section here</div> : null}
            </Column>
          </SortableContext>
        ))}
      </div>
      <DragOverlay dropAnimation={{duration: 220, easing: 'cubic-bezier(.2,.8,.2,1)'}}>
        {activeDef ? (
          <div className="nv-drag-ghost">
            <GripVertical size={16} aria-hidden="true" />
            <activeDef.icon size={16} aria-hidden="true" />
            <strong>{activeDef.title}</strong>
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
