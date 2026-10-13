import { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, XCircle, ArrowUpDown, Bot, ExternalLink } from 'lucide-react';
import { api } from '../api';
import {
  useApi, formatDate, formatMoney, getInitials, getSegmentInfo,
  daysSince, matchesQuery, notifyDataChanged,
} from '../utils';
import {
  KpiStrip, Pill, ViewToggle, Column, Avatar, CardDate, InactiveFlag,
  DropDock, Drawer, Toast, Loading, ErrorBox, useSearch,
} from '../components/board';

// One board column per agent output type. Rules decide the type; humans decide the outcome.
const COLUMNS = [
  { type: 'segment_change', title: 'Segment change' },
  { type: 'follow_up_email', title: 'Follow-up email' },
  { type: 'issue_alert', title: 'Order issue' },
];

const STATUS_PILLS = [
  { value: 'pending', label: 'Pending' },
  { value: 'executed', label: 'Executed' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: '', label: 'All' },
];

const AGENT_LABELS = {
  segment_agent: 'Segment agent',
  follow_up_agent: 'Follow-up agent',
  order_issue_watcher: 'Issue watcher',
  issue_watcher: 'Issue watcher',
  shop_copilot: 'Shop Copilot',
};

/**
 * If the proposal's draft is the {subject, body} JSON produced by the
 * Ollama / LM Studio providers, render it as a readable email.  Plain-text
 * FakeLLM drafts are left verbatim.
 */
export function renderDraft(text) {
  let d = null;
  if (text && typeof text === 'string') {
    try { d = JSON.parse(text); } catch { d = null; }
  }
  if (d && d.subject && d.body) {
    return (
      <div className="draft-email">
        <div className="draft-email-subject">{d.subject}</div>
        <div className="draft-email-body">{d.body}</div>
      </div>
    );
  }
  return <div className="prose-box">{text}</div>;
}

const fullName = (c) => (c ? `${c.first_name} ${c.last_name}`.trim() : 'Unknown customer');

export default function Proposals() {
  const { query } = useSearch();
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState('pending');
  const [view, setView] = useState('board');
  const [dragging, setDragging] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState('');
  const clearToast = useCallback(() => setToast(''), []);

  const { data: proposals, loading, error, refetch } = useApi(() => api.getProposals());
  const { data: customers } = useApi(() => api.getCustomers());
  const [searchParams, setSearchParams] = useSearchParams();

  // Deep link from Copilot: /proposals?open=33 opens that proposal's drawer.
  const openId = Number(searchParams.get('open')) || null;
  const retried = useRef(false);
  useEffect(() => {
    if (!openId) return;
    const match = proposals?.find((x) => x.id === openId);
    if (match) {
      setStatusFilter(match.status === 'pending' ? 'pending' : '');
      setSelected(match);
      setSearchParams({}, { replace: true });
    } else if (proposals && !retried.current) {
      retried.current = true;
      refetch(); // created a moment ago: fetch once more
    }
  }, [openId, proposals]); // eslint-disable-line react-hooks/exhaustive-deps

  const customerById = useMemo(
    () => Object.fromEntries((customers || []).map((c) => [c.id, c])),
    [customers]
  );

  const all = proposals || [];
  const counts = useMemo(() => {
    const c = { '': all.length };
    for (const p of all) c[p.status] = (c[p.status] || 0) + 1;
    return c;
  }, [all]);

  const visible = all.filter((p) => {
    if (statusFilter && p.status !== statusFilter) return false;
    const c = customerById[p.customer_id];
    return matchesQuery(query, p.title, p.summary, p.agent_name, fullName(c), c?.email);
  });

  async function review(id, action) {
    const p = all.find((x) => x.id === id);
    if (!p || p.status !== 'pending') return;
    setBusy(true);
    try {
      await api.reviewProposal(id, action);
      setToast(`${action === 'approve' ? 'Approved' : 'Rejected'}: ${p.title}`);
      setSelected(null);
      await refetch();
      notifyDataChanged();
    } catch (e) {
      setToast(`Couldn't ${action}: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (loading && !proposals) return <Loading />;
  if (error) return <ErrorBox message={error} />;

  // KPIs
  const done = (counts.executed || 0) + (counts.approved || 0);
  const reviewed = done + (counts.rejected || 0);
  const approvalRate = reviewed ? Math.round((done / reviewed) * 100) : 0;
  const llmShare = all.length ? Math.round((all.filter((p) => p.is_llm_generated).length / all.length) * 100) : 0;
  const pending = all.filter((p) => p.status === 'pending');
  const pendingValue = pending.reduce((s, p) => s + (customerById[p.customer_id]?.total_spent || 0), 0);

  const kpis = [
    { label: 'Awaiting review', value: counts.pending || 0, sub: `${formatMoney(pendingValue)} in customers` },
    { label: 'Executed', value: counts.executed || 0 },
    { label: 'Approval rate', value: `${approvalRate}%`, sub: `${reviewed} reviewed` },
    { label: 'Written by LLM', value: `${llmShare}%`, sub: 'rules decide, LLM writes' },
  ];
  const volume = {
    title: 'Pending by agent',
    total: `${pending.length} proposals`,
    parts: COLUMNS.map((col) => ({
      label: col.title,
      value: pending.filter((p) => p.proposal_type === col.type).length,
    })),
  };

  const maxColumn = Math.max(1, ...COLUMNS.map((col) => visible.filter((p) => p.proposal_type === col.type).length));

  return (
    <div className="animate-in">
      <KpiStrip kpis={kpis} volume={volume} />

      <div className="toolbar">
        {STATUS_PILLS.map((s) => (
          <Pill
            key={s.value}
            active={statusFilter === s.value}
            count={counts[s.value] || 0}
            onClick={() => setStatusFilter(s.value)}
          >
            {s.label}
          </Pill>
        ))}
        <div className="toolbar-spacer" />
        <span className="sort-label"><ArrowUpDown size={14} /> Newest first</span>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {view === 'board' ? (
        <div className="board">
          {COLUMNS.map((col) => {
            const items = visible.filter((p) => p.proposal_type === col.type);
            const value = items.reduce((s, p) => s + (customerById[p.customer_id]?.total_spent || 0), 0);
            const llm = items.filter((p) => p.is_llm_generated).length;
            return (
              <Column
                key={col.type}
                title={col.title}
                count={items.length}
                meta={<><strong>{formatMoney(value)}</strong> · {items.length ? Math.round((llm / items.length) * 100) : 0}% LLM-written</>}
                progress={(items.length / maxColumn) * 100}
                highlight={dragging && dragging.type === col.type}
                empty={statusFilter === 'pending' ? 'All caught up' : 'Nothing here'}
              >
                {items.map((p) => (
                  <ProposalCard
                    key={p.id}
                    proposal={p}
                    customer={customerById[p.customer_id]}
                    isDragging={dragging?.id === p.id}
                    onOpen={() => setSelected(p)}
                    onDragStart={() => setDragging({ id: p.id, type: p.proposal_type })}
                    onDragEnd={() => setDragging(null)}
                  />
                ))}
              </Column>
            );
          })}
        </div>
      ) : (
        <div className="page-body">
          <table className="data-table">
            <thead>
              <tr><th>Proposal</th><th>Customer</th><th>Agent</th><th>Text by</th><th>Status</th><th>Created</th></tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <tr key={p.id} className="clickable" onClick={() => setSelected(p)}>
                  <td style={{ fontWeight: 500 }}>{p.title}</td>
                  <td>{fullName(customerById[p.customer_id])}</td>
                  <td>{AGENT_LABELS[p.agent_name] || p.agent_name}</td>
                  <td>{p.is_llm_generated ? 'LLM' : 'Rules'}</td>
                  <td><span className={`status-badge ${p.status}`}>{p.status}</span></td>
                  <td style={{ color: 'var(--text-muted)' }}>{formatDate(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!visible.length && <div className="empty-state"><p>No proposals match.</p></div>}
        </div>
      )}

      <DropDock
        open={!!dragging}
        onDrop={(id, action) => { setDragging(null); review(id, action); }}
      />

      {selected && (
        <ProposalDrawer
          proposal={selected}
          customer={customerById[selected.customer_id]}
          busy={busy}
          onClose={() => setSelected(null)}
          onReview={review}
          onCustomer={() => navigate(`/customers/${selected.customer_id}`)}
        />
      )}

      <Toast message={toast} onDone={clearToast} />
    </div>
  );
}

function ProposalCard({ proposal: p, customer, isDragging, onOpen, onDragStart, onDragEnd }) {
  const draggable = p.status === 'pending';
  const waiting = daysSince(p.created_at);
  const seg = customer ? getSegmentInfo(customer.segment) : null;

  return (
    <article
      className={`deal-card ${isDragging ? 'dragging' : ''} ${p.status === 'rejected' ? 'muted' : ''}`}
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', String(p.id));
        e.dataTransfer.effectAllowed = 'move';
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      onClick={onOpen}
      title={draggable ? 'Drag onto Approve or Reject, or click for details' : 'Click for details'}
    >
      <div className="chips">
        <span className="chip">{AGENT_LABELS[p.agent_name] || p.agent_name}</span>
        <span className={`chip ${p.is_llm_generated ? 'accent' : ''}`}>
          {p.is_llm_generated ? 'LLM' : 'Rules'}
        </span>
        {p.status !== 'pending' && (
          <span className={`chip ${p.status === 'rejected' ? 'danger' : 'success'}`}>{p.status}</span>
        )}
      </div>
      <div className="deal-title">{p.title}</div>
      <div className="deal-sub">
        {customer ? `${customer.first_name} ${customer.last_name}` : `Customer #${p.customer_id}`}
        {seg && <><span className="dot">·</span>{seg.label}</>}
      </div>
      <div className="deal-foot">
        <span className="deal-amount">{customer ? formatMoney(customer.total_spent) : '—'}</span>
        {p.status === 'pending' && waiting >= 3
          ? <InactiveFlag days={waiting} label="waiting" />
          : <CardDate date={p.created_at} />}
        <Avatar
          text={customer ? getInitials(customer.first_name, customer.last_name) : '?'}
          title={customer?.email}
        />
      </div>
    </article>
  );
}

function ProposalDrawer({ proposal: p, customer, busy, onClose, onReview, onCustomer }) {
  const draft = p.proposed_action?.draft;
  const isEmail = p.proposal_type === 'follow_up_email';

  return (
    <Drawer
      title={p.title}
      onClose={onClose}
      footer={p.status === 'pending' ? (
        <>
          <button className="btn btn-success" disabled={busy} onClick={() => onReview(p.id, 'approve')}>
            <CheckCircle2 size={16} /> {busy ? 'Working...' : 'Approve'}
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => onReview(p.id, 'reject')}>
            <XCircle size={16} /> Reject
          </button>
        </>
      ) : null}
    >
      <div className="chips" style={{ marginBottom: 0 }}>
        <span className={`status-badge ${p.status}`}>{p.status}</span>
        <span className="chip"><Bot size={12} style={{ verticalAlign: '-2px' }} /> {AGENT_LABELS[p.agent_name] || p.agent_name}</span>
        <span className={`chip ${p.is_llm_generated ? 'accent' : ''}`}>
          {p.is_llm_generated ? `LLM · ${p.evidence?.llm_model || 'model'}` : 'Rule-based template'}
        </span>
      </div>

      <div>
        <div className="section-label">Customer</div>
        <button className="btn btn-sm" onClick={onCustomer}>
          {customer ? `${customer.first_name} ${customer.last_name} · ${customer.email}` : `Customer #${p.customer_id}`}
          <ExternalLink size={13} />
        </button>
      </div>

      <div>
        <div className="section-label">Summary</div>
        <div className="prose-box">{p.summary}</div>
      </div>

      {isEmail && draft !== undefined ? (
        <div>
          <div className="section-label">{p.is_llm_generated ? 'Draft email (LLM)' : 'Draft email (template)'}</div>
          {renderDraft(draft)}
        </div>
      ) : p.llm_explanation ? (
        <div>
          <div className="section-label">{p.is_llm_generated ? 'Explanation (LLM)' : 'Explanation (rules)'}</div>
          <div className="prose-box">{p.llm_explanation}</div>
        </div>
      ) : null}

      <div className="proposal-evidence">
        <div className="section-label">Evidence the rules used</div>
        <pre>{JSON.stringify(p.evidence, null, 2)}</pre>
      </div>
      <div className="proposal-evidence">
        <div className="section-label">Proposed action</div>
        <pre>{JSON.stringify(p.proposed_action, null, 2)}</pre>
      </div>

      {p.reviewed_by && (
        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
          Reviewed by {p.reviewed_by} on {formatDate(p.reviewed_at)}
          {p.executed_at && <> · executed {formatDate(p.executed_at)}</>}
        </div>
      )}
    </Drawer>
  );
}
