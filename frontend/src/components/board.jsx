/**
 * Shared building blocks for the pipeline-board pages
 * (Approval Inbox, Customers, Orders).
 */
import { createContext, useContext, useEffect, useState } from 'react';
import { Calendar, CheckCircle2, XCircle, X, LayoutGrid, List, Hourglass } from 'lucide-react';
import { formatShortDate, isToday } from '../utils';

// Global search text from the top bar, read by every board page.
export const SearchContext = createContext({ query: '', setQuery: () => {} });
export const useSearch = () => useContext(SearchContext);

// Light → full accent ramp, one colour per stage/column.
export const STAGE_COLORS = ['var(--stage-1)', 'var(--stage-2)', 'var(--stage-3)', 'var(--stage-4)', 'var(--stage-5)'];

export function KpiStrip({ kpis, volume }) {
  return (
    <div className="kpi-strip">
      {kpis.map((k) => (
        <div className="kpi" key={k.label}>
          <span className="kpi-label">{k.label}</span>
          <span className="kpi-value">
            {k.value}
            {k.sub && <span className={`kpi-sub ${k.up ? 'up' : ''}`}>{k.sub}</span>}
          </span>
        </div>
      ))}
      {volume && (
        <>
          <div className="kpi-divider" />
          <StageVolume {...volume} />
        </>
      )}
    </div>
  );
}

/** "Volume by stage" stacked bar with legend. parts: [{label, value}] */
export function StageVolume({ title, total, parts }) {
  const sum = parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <div className="stage-volume">
      <div className="stage-volume-head">
        <span>{title}</span>
        <strong>{total}</strong>
      </div>
      <div className="stage-bar">
        {parts.map((p, i) => (
          <span
            key={p.label}
            title={`${p.label}: ${p.value}`}
            style={{ flex: Math.max(p.value / sum, 0.01), background: STAGE_COLORS[i % STAGE_COLORS.length] }}
          />
        ))}
      </div>
      <div className="stage-legend">
        {parts.map((p, i) => (
          <span key={p.label}>
            <i style={{ background: STAGE_COLORS[i % STAGE_COLORS.length] }} />
            {p.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Pill({ active, count, onClick, children, ghost }) {
  return (
    <button className={`pill ${active ? 'active' : ''} ${ghost ? 'ghost' : ''}`} onClick={onClick}>
      {children}
      {count !== undefined && <span className="count">{count}</span>}
    </button>
  );
}

export function ViewToggle({ view, onChange }) {
  return (
    <div className="view-toggle">
      <button className={view === 'board' ? 'active' : ''} onClick={() => onChange('board')}>
        <LayoutGrid size={14} /> Board
      </button>
      <button className={view === 'list' ? 'active' : ''} onClick={() => onChange('list')}>
        <List size={14} /> List
      </button>
    </div>
  );
}

export function Column({ title, count, meta, progress, highlight, children, empty = 'Nothing here' }) {
  return (
    <section className={`column ${highlight ? 'highlight' : ''}`}>
      <div className="column-head">
        <div className="column-title">
          {title} <span className="column-count">{count}</span>
        </div>
        {meta && <div className="column-meta">{meta}</div>}
        {progress !== undefined && (
          <div className="column-progress">
            <span style={{ width: `${Math.min(100, Math.max(2, progress))}%` }} />
          </div>
        )}
      </div>
      {count === 0 ? <div className="column-empty">{empty}</div> : children}
    </section>
  );
}

export function Avatar({ text, title }) {
  return <span className="avatar" title={title}>{text}</span>;
}

/** Card date with the orange "today" highlight. */
export function CardDate({ date }) {
  return (
    <span className={`deal-date ${isToday(date) ? 'hot' : ''}`}>
      <Calendar size={13} /> {formatShortDate(date)}
    </span>
  );
}

export function InactiveFlag({ days, label = 'inactive' }) {
  return (
    <span className="flag"><Hourglass size={12} /> {days}d {label}</span>
  );
}

/** Approve / Reject dock that slides up while a card is being dragged. */
export function DropDock({ open, onDrop }) {
  const [over, setOver] = useState(null);
  useEffect(() => { if (!open) setOver(null); }, [open]);

  const zone = (action, label, Icon) => (
    <div
      className={`drop-zone ${action} ${over === action ? 'over' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setOver(action); }}
      onDragLeave={() => setOver(null)}
      onDrop={(e) => {
        e.preventDefault();
        const id = Number(e.dataTransfer.getData('text/plain'));
        setOver(null);
        if (id) onDrop(id, action);
      }}
    >
      <Icon size={18} /> {label}
    </div>
  );

  return (
    <div className={`drop-dock ${open ? 'open' : ''}`}>
      {zone('approve', 'Approve', CheckCircle2)}
      {zone('reject', 'Reject', XCircle)}
    </div>
  );
}

export function Drawer({ title, onClose, children, footer }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={title}>
        <div className="drawer-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </>
  );
}

export function Toast({ message, onDone }) {
  useEffect(() => {
    if (!message) return undefined;
    const t = setTimeout(onDone, 2200);
    return () => clearTimeout(t);
  }, [message, onDone]);
  return message ? <div className="toast">{message}</div> : null;
}

export function Loading() {
  return <div className="loading-container"><div className="loading-spinner" /></div>;
}

export function ErrorBox({ message }) {
  return (
    <div className="loading-container">
      <p>Error: {message}</p>
      <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Make sure the backend is running on port 8000.</p>
    </div>
  );
}
