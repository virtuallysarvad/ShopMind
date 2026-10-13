import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api';
import { useApi, formatCurrency, formatDate, getSegmentInfo, getInitials } from '../utils';
import { ArrowLeft, Mail, Phone, Calendar, ShoppingCart, DollarSign } from 'lucide-react';

export default function CustomerDetail() {
  const { id } = useParams();
  const [tab, setTab] = useState('timeline');

  const { data: customer, loading, error } = useApi(() => api.getCustomer(id), [id]);
  const { data: orders } = useApi(() => api.getOrders(id), [id]);
  const { data: timeline } = useApi(() => api.getTimeline(id), [id]);
  const { data: proposals } = useApi(() => api.getProposals(), []);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner" />
      </div>
    );
  }

  if (error || !customer) {
    return (
      <div className="loading-container">
        <p>Error: {error || 'Customer not found'}</p>
      </div>
    );
  }

  const segInfo = getSegmentInfo(customer.segment);
  const customerProposals = proposals?.filter((p) => p.customer_id === customer.id) || [];

  return (
    <div className="animate-in page-body">
      <Link to="/customers" className="btn btn-outline btn-sm" style={{ marginBottom: '20px' }}>
        <ArrowLeft size={14} /> Back to Customers
      </Link>

      <div className="customer-header">
        <div className="customer-avatar">
          {getInitials(customer.first_name, customer.last_name)}
        </div>
        <div className="customer-info">
          <h2>{customer.first_name} {customer.last_name}</h2>
          <p style={{ display: 'flex', gap: '16px', alignItems: 'center', marginTop: '4px' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Mail size={14} /> {customer.email}
            </span>
            {customer.phone && (
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Phone size={14} /> {customer.phone}
              </span>
            )}
            <span className={`segment-badge ${segInfo.color}`}>
              {segInfo.icon} {segInfo.label}
            </span>
          </p>
        </div>
      </div>

      <div className="customer-stats">
        <div className="stat-card">
          <div className="stat-icon blue"><ShoppingCart size={20} /></div>
          <div className="stat-value">{customer.order_count}</div>
          <div className="stat-label">Orders</div>
        </div>
        <div className="stat-card">
          <div className="stat-icon green"><DollarSign size={20} /></div>
          <div className="stat-value">{formatCurrency(customer.total_spent)}</div>
          <div className="stat-label">Total Spent</div>
        </div>
        <div className="stat-card">
          <div className="stat-icon purple"><Calendar size={20} /></div>
          <div className="stat-value" style={{ fontSize: '1rem' }}>
            {formatDate(customer.first_order_date)}
          </div>
          <div className="stat-label">First Order</div>
        </div>
        <div className="stat-card">
          <div className="stat-icon yellow"><Calendar size={20} /></div>
          <div className="stat-value" style={{ fontSize: '1rem' }}>
            {formatDate(customer.last_order_date)}
          </div>
          <div className="stat-label">Last Order</div>
        </div>
      </div>

      <div className="detail-tabs">
        <button className={`detail-tab ${tab === 'timeline' ? 'active' : ''}`} onClick={() => setTab('timeline')}>
          Timeline
        </button>
        <button className={`detail-tab ${tab === 'orders' ? 'active' : ''}`} onClick={() => setTab('orders')}>
          Orders ({orders?.length || 0})
        </button>
        <button className={`detail-tab ${tab === 'proposals' ? 'active' : ''}`} onClick={() => setTab('proposals')}>
          Proposals ({customerProposals.length})
        </button>
      </div>

      <div className="card">
        {tab === 'timeline' && <TimelineView events={timeline} />}
        {tab === 'orders' && <OrdersView orders={orders} />}
        {tab === 'proposals' && <ProposalsView proposals={customerProposals} />}
      </div>
    </div>
  );
}

function TimelineView({ events }) {
  if (!events?.length) {
    return <div className="empty-state"><div className="empty-state-icon">📅</div><p>No timeline events</p></div>;
  }

  return (
    <div className="timeline">
      {events.map((e) => {
        let dotClass = '';
        if (e.event_type.includes('order')) dotClass = 'order';
        else if (e.event_type.includes('segment')) dotClass = 'segment';
        else if (e.event_type.includes('proposal')) dotClass = 'proposal';
        else if (e.event_type.includes('issue')) dotClass = 'issue';

        return (
          <div key={e.id} className="timeline-item">
            <div className={`timeline-dot ${dotClass}`} />
            <div className="timeline-title">{e.title}</div>
            <div className="timeline-desc">{e.description}</div>
            <div className="timeline-time">{formatDate(e.created_at)}</div>
          </div>
        );
      })}
    </div>
  );
}

function OrdersView({ orders }) {
  if (!orders?.length) {
    return <div className="empty-state"><div className="empty-state-icon">📦</div><p>No orders</p></div>;
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Order ID</th>
          <th>Status</th>
          <th>Total</th>
          <th>Payment</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.id}>
            <td style={{ fontWeight: 600 }}>#{o.woo_order_id}</td>
            <td><span className={`status-badge ${o.status}`}>{o.status}</span></td>
            <td>{formatCurrency(o.total)}</td>
            <td style={{ color: 'var(--text-secondary)' }}>{o.payment_method || '—'}</td>
            <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>{formatDate(o.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ProposalsView({ proposals }) {
  if (!proposals?.length) {
    return <div className="empty-state"><div className="empty-state-icon">🤖</div><p>No proposals for this customer</p></div>;
  }

  return (
    <div>
      {proposals.map((p) => (
        <div key={p.id} className="proposal-card" style={{ margin: '0 0 12px' }}>
          <div className="proposal-header">
            <div>
              <div className="proposal-title">{p.title}</div>
              <div className="proposal-agent">by {p.agent_name}</div>
            </div>
            <span className={`status-badge ${p.status}`}>{p.status}</span>
          </div>
          <div className="proposal-summary">{p.summary}</div>
        </div>
      ))}
    </div>
  );
}
