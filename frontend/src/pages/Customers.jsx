import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useApi, formatCurrency, getSegmentInfo, getInitials } from '../utils';
import { Users, Filter } from 'lucide-react';

export default function Customers() {
  const [segmentFilter, setSegmentFilter] = useState('');
  const { data: customers, loading, error } = useApi(
    () => api.getCustomers(segmentFilter || undefined),
    [segmentFilter]
  );

  return (
    <div className="animate-in">
      <div className="page-header">
        <h2>Customers</h2>
        <p>All customers with AI-powered segmentation</p>
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <Filter size={16} style={{ color: 'var(--text-muted)' }} />
          <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginRight: '8px' }}>
            Filter by segment:
          </span>
          {['', 'new', 'regular', 'vip', 'at_risk'].map((seg) => {
            const label = seg ? getSegmentInfo(seg).label : 'All';
            return (
              <button
                key={seg}
                className={`btn btn-sm ${segmentFilter === seg ? 'btn-primary' : 'btn-outline'}`}
                onClick={() => setSegmentFilter(seg)}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card">
        {loading ? (
          <div className="loading-container">
            <div className="loading-spinner" />
          </div>
        ) : error ? (
          <div className="loading-container">
            <p>Error: {error}</p>
          </div>
        ) : customers?.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">👥</div>
            <p>No customers found</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Customer</th>
                <th>Email</th>
                <th>Segment</th>
                <th>Orders</th>
                <th>Total Spent</th>
              </tr>
            </thead>
            <tbody>
              {customers?.map((c) => {
                const segInfo = getSegmentInfo(c.segment);
                return (
                  <tr key={c.id}>
                    <td>
                      <Link
                        to={`/customers/${c.id}`}
                        style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none', color: 'inherit' }}
                      >
                        <div className="customer-avatar" style={{ width: 36, height: 36, fontSize: '0.8rem' }}>
                          {getInitials(c.first_name, c.last_name)}
                        </div>
                        <span style={{ fontWeight: 600 }}>
                          {c.first_name} {c.last_name}
                        </span>
                      </Link>
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>{c.email}</td>
                    <td>
                      <span className={`segment-badge ${segInfo.color}`}>
                        {segInfo.icon} {segInfo.label}
                      </span>
                    </td>
                    <td>{c.order_count}</td>
                    <td>{formatCurrency(c.total_spent)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
