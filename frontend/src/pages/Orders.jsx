import { Link } from 'react-router-dom';
import { api } from '../api';
import { useApi, formatCurrency, formatDate } from '../utils';
import { ShoppingCart } from 'lucide-react';

export default function Orders() {
  const { data: orders, loading, error } = useApi(() => api.getOrders());

  return (
    <div className="animate-in">
      <div className="page-header">
        <h2>Orders</h2>
        <p>All orders ingested from WooCommerce</p>
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
        ) : !orders?.length ? (
          <div className="empty-state">
            <div className="empty-state-icon">📦</div>
            <p>No orders yet. Seed the database first.</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Customer</th>
                <th>Status</th>
                <th>Total</th>
                <th>Payment</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td style={{ fontWeight: 600 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <ShoppingCart size={15} style={{ color: 'var(--text-muted)' }} />
                      #{o.woo_order_id}
                    </div>
                  </td>
                  <td>
                    <Link
                      to={`/customers/${o.customer_id}`}
                      style={{ color: 'var(--accent-primary)', textDecoration: 'none' }}
                    >
                      Customer #{o.customer_id}
                    </Link>
                  </td>
                  <td>
                    <span className={`status-badge ${o.status}`}>{o.status}</span>
                  </td>
                  <td>{formatCurrency(o.total, o.currency)}</td>
                  <td style={{ color: 'var(--text-secondary)' }}>{o.payment_method || '—'}</td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    {formatDate(o.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
