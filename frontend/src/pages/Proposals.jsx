import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useApi, formatDate } from '../utils';
import { Inbox, CheckCircle, XCircle, Clock, Bot } from 'lucide-react';

/**
 * If the proposal's draft is the {subject, body} JSON produced by the
 * Ollama / LM Studio providers, render it as a readable email.  Plain-text
 * FakeLLM drafts (Subject: … with no JSON body object) are left verbatim.
 */
function renderDraft(text) {
  const d = (text && typeof text === 'string') ? (function () {
    try { return JSON.parse(text); } catch { return null; }
  })() : null;
  if (d && d.subject && d.body) {
    return (
      <div className="draft-email">
        <div className="draft-email-subject">{d.subject}</div>
        <div className="draft-email-body">{d.body}</div>
      </div>
    );
  }
  return <pre>{text}</pre>;
}

export default function Proposals() {
  const [statusFilter, setStatusFilter] = useState('');
  const { data: proposals, loading, error, refetch } = useApi(
    () => api.getProposals(statusFilter || undefined),
    [statusFilter]
  );
  const [reviewing, setReviewing] = useState(null);

  async function handleReview(proposalId, action) {
    setReviewing(proposalId);
    try {
      await api.reviewProposal(proposalId, action);
      await refetch();
    } catch (e) {
      alert(`Error: ${e.message}`);
    } finally {
      setReviewing(null);
    }
  }

  return (
    <div className="animate-in">
      <div className="page-header">
        <h2>Approval Inbox</h2>
        <p>Review and approve AI agent proposals before execution</p>
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <Inbox size={16} style={{ color: 'var(--text-muted)' }} />
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginRight: '8px' }}>
            Filter:
          </span>
          {[
            { value: '', label: 'All' },
            { value: 'pending', label: '⏳ Pending' },
            { value: 'approved', label: '✅ Approved' },
            { value: 'rejected', label: '❌ Rejected' },
            { value: 'executed', label: '🚀 Executed' },
          ].map(({ value, label }) => (
            <button
              key={value}
              className={`btn btn-sm ${statusFilter === value ? 'btn-primary' : 'btn-outline'}`}
              onClick={() => setStatusFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="loading-container">
          <div className="loading-spinner" />
        </div>
      ) : error ? (
        <div className="loading-container">
          <p>Error: {error}</p>
        </div>
      ) : !proposals?.length ? (
        <div className="card">
          <div className="empty-state">
            <div className="empty-state-icon">📭</div>
            <p>No proposals found</p>
          </div>
        </div>
      ) : (
        proposals.map((p) => (
          <ProposalCard
            key={p.id}
            proposal={p}
            onReview={handleReview}
            reviewing={reviewing === p.id}
          />
        ))
      )}
    </div>
  );
}

function ProposalCard({ proposal: p, onReview, reviewing }) {
  const [expanded, setExpanded] = useState(false);

  const typeIcons = {
    segment_change: '🔄',
    follow_up_email: '✉️',
    issue_alert: '🚨',
  };

  return (
    <div className="proposal-card">
      <div className="proposal-header">
        <div>
          <div className="proposal-title">
            <span style={{ marginRight: '8px' }}>{typeIcons[p.proposal_type] || '🤖'}</span>
            {p.title}
          </div>
          <div className="proposal-agent">
            <Bot size={12} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
            {p.agent_name}
            {p.is_llm_generated && (
              <span style={{ marginLeft: '8px', color: 'var(--accent-primary)', fontSize: '0.7rem' }}>
                🧠 LLM Generated
              </span>
            )}
            {!p.is_llm_generated && (
              <span style={{ marginLeft: '8px', color: 'var(--text-muted)', fontSize: '0.7rem' }}>
                📏 Rule-based
              </span>
            )}
          </div>
        </div>
        <span className={`status-badge ${p.status}`}>{p.status}</span>
      </div>

      <div className="proposal-summary">{p.summary}</div>

      <div style={{ marginBottom: '12px' }}>
        <Link
          to={`/customers/${p.customer_id}`}
          style={{ color: 'var(--accent-primary)', textDecoration: 'none', fontSize: '0.82rem' }}
        >
          View Customer →
        </Link>
      </div>

      <button
        className="btn btn-outline btn-sm"
        onClick={() => setExpanded(!expanded)}
        style={{ marginBottom: expanded ? '12px' : '0' }}
      >
        {expanded ? 'Hide Details' : 'Show Details'}
      </button>

      {expanded && (
        <>
          <div className="proposal-evidence">
            <h4>Evidence</h4>
            <pre>{JSON.stringify(p.evidence, null, 2)}</pre>
          </div>
          <div className="proposal-evidence">
            <h4>Proposed Action</h4>
            <pre>{JSON.stringify(p.proposed_action, null, 2)}</pre>
          </div>
          {p.llm_explanation && (
            <div className="proposal-evidence">
              <h4>
                {p.is_llm_generated ? '🧠 LLM Explanation' : '📏 Deterministic Explanation'}
              </h4>
              <pre>{p.llm_explanation}</pre>
            </div>
          )}
          {p.proposed_action?.draft !== undefined && (
            <div className="proposal-evidence">
              <h4>
                {p.is_llm_generated
                  ? '✉️ Draft Email'
                  : p.llm_explanation.startsWith('Subject:')
                    ? '📏 Deterministic Draft'
                    : '📦 Draft'}
              </h4>
              {renderDraft(p.proposed_action.draft)}
            </div>
          )}
        </>
      )}

      {p.status === 'pending' && (
        <div className="proposal-actions" style={{ marginTop: '16px' }}>
          <button
            className="btn btn-success btn-sm"
            disabled={reviewing}
            onClick={() => onReview(p.id, 'approve')}
          >
            <CheckCircle size={14} />
            {reviewing ? 'Processing...' : 'Approve'}
          </button>
          <button
            className="btn btn-danger btn-sm"
            disabled={reviewing}
            onClick={() => onReview(p.id, 'reject')}
          >
            <XCircle size={14} />
            Reject
          </button>
          <span className="proposal-meta">
            <Clock size={12} style={{ display: 'inline', verticalAlign: 'middle' }} />{' '}
            {formatDate(p.created_at)}
          </span>
        </div>
      )}

      {p.status !== 'pending' && p.reviewed_by && (
        <div style={{ marginTop: '12px', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          Reviewed by {p.reviewed_by} on {formatDate(p.reviewed_at)}
        </div>
      )}
    </div>
  );
}
