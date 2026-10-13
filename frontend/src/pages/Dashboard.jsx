import { api } from '../api';
import { useApi, formatCurrency, getSegmentInfo } from '../utils';
import { Link } from 'react-router-dom';
import { 
  Users, ShoppingCart, DollarSign, AlertCircle, 
  TrendingUp, ArrowRight 
} from 'lucide-react';

export default function Dashboard() {
  const { data, loading, error } = useApi(() => api.getDashboard());

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;

  const stats = data;

  return (
    <div className="animate-in">
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Overview of your store's AI-powered CRM</p>
      </div>

      <div className="stats-grid">
        <StatCard
          icon={<Users size={22} />}
          iconClass="purple"
          value={stats.total_customers}
          label="Total Customers"
        />
        <StatCard
          icon={<ShoppingCart size={22} />}
          iconClass="blue"
          value={stats.total_orders}
          label="Total Orders"
        />
        <StatCard
          icon={<DollarSign size={22} />}
          iconClass="green"
          value={formatCurrency(stats.total_revenue)}
          label="Total Revenue"
        />
        <StatCard
          icon={<AlertCircle size={22} />}
          iconClass="yellow"
          value={stats.pending_proposals}
          label="Pending Proposals"
          highlight={stats.pending_proposals > 0}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Customer Segments</span>
            <Link to="/customers" className="btn btn-outline btn-sm">
              View All <ArrowRight size={14} />
            </Link>
          </div>
          <SegmentDistribution distribution={stats.segment_distribution} total={stats.total_customers} />
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Recent Orders</span>
            <Link to="/orders" className="btn btn-outline btn-sm">
              View All <ArrowRight size={14} />
            </Link>
          </div>
          {stats.recent_orders?.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Status</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent_orders.map((order) => (
                  <tr key={order.id}>
                    <td>#{order.woo_order_id}</td>
                    <td>
                      <span className={`status-badge ${order.status}`}>
                        {order.status}
                      </span>
                    </td>
                    <td>{formatCurrency(order.total, order.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">📦</div>
              <p>No orders yet</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ icon, iconClass, value, label, highlight }) {
  return (
    <div className="stat-card" style={highlight ? { borderColor: 'var(--warning)' } : {}}>
      <div className={`stat-icon ${iconClass}`}>{icon}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function SegmentDistribution({ distribution, total }) {
  const segments = ['new', 'regular', 'vip', 'at_risk'];
  if (total === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">📊</div>
        <p>No customer data yet</p>
      </div>
    );
  }

  return (
    <div className="segment-distribution" style={{ flexDirection: 'column', gap: '16px' }}>
      {segments.map((seg) => {
        const count = distribution[seg] || 0;
        const pct = total > 0 ? (count / total) * 100 : 0;
        const info = getSegmentInfo(seg);
        return (
          <div key={seg} className="segment-bar-container">
            <div className="segment-bar-label">
              <span>{info.icon} {info.label}</span>
              <span>{count} ({pct.toFixed(0)}%)</span>
            </div>
            <div className="segment-bar">
              <div
                className={`segment-bar-fill ${seg}`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="loading-container">
      <div className="loading-spinner" />
      <p>Loading dashboard...</p>
    </div>
  );
}

function ErrorState({ message }) {
  return (
    <div className="loading-container">
      <div style={{ fontSize: '2rem', marginBottom: '12px' }}>⚠️</div>
      <p>Error: {message}</p>
      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '8px' }}>
        Make sure the backend is running on port 8000
      </p>
    </div>
  );
}
