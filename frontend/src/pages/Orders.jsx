import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpDown } from 'lucide-react';
import { api } from '../api';
import { useApi, formatMoney, formatCurrency, formatDate, getInitials, daysSince, matchesQuery } from '../utils';
import {
  KpiStrip, Pill, ViewToggle, Column, Avatar, CardDate, InactiveFlag,
  Loading, ErrorBox, useSearch,
} from '../components/board';

// WooCommerce order statuses, grouped into board columns in lifecycle order.
const COLUMNS = [
  { key: 'pending', title: 'Pending', statuses: ['pending', 'on-hold'] },
  { key: 'processing', title: 'Processing', statuses: ['processing'] },
  { key: 'completed', title: 'Completed', statuses: ['completed'] },
  { key: 'problem', title: 'Failed / refunded', statuses: ['failed', 'refunded', 'cancelled'] },
];

const PILLS = [
  { value: 'open', label: 'Open', statuses: ['pending', 'on-hold', 'processing'] },
  { value: 'completed', label: 'Completed', statuses: ['completed'] },
  { value: 'problem', label: 'Problems', statuses: ['failed', 'refunded', 'cancelled'] },
  { value: '', label: 'All', statuses: null },
];

const itemsLabel = (o) => {
  const items = o.line_items || [];
  if (!items.length) return 'No line items';
  const first = items[0]?.name || 'Item';
  return items.length > 1 ? `${first} +${items.length - 1}` : first;
};

export default function Orders() {
  const { query } = useSearch();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('');
  const [view, setView] = useState('board');

  const { data: orders, loading, error } = useApi(() => api.getOrders());
  const { data: customers } = useApi(() => api.getCustomers());
  const customerById = useMemo(
    () => Object.fromEntries((customers || []).map((c) => [c.id, c])),
    [customers]
  );

  if (loading && !orders) return <Loading />;
  if (error) return <ErrorBox message={error} />;

  const all = orders || [];
  const pill = PILLS.find((p) => p.value === filter);
  const visible = all.filter((o) => {
    if (pill?.statuses && !pill.statuses.includes(o.status)) return false;
    const c = customerById[o.customer_id];
    return matchesQuery(query, o.woo_order_id, c?.first_name, c?.last_name, c?.email, itemsLabel(o), o.status);
  });

  const sum = (list) => list.reduce((s, o) => s + o.total, 0);
  const completed = all.filter((o) => o.status === 'completed');
  const problems = all.filter((o) => ['failed', 'refunded', 'cancelled'].includes(o.status));
  const open = all.filter((o) => ['pending', 'on-hold', 'processing'].includes(o.status));

  const kpis = [
    { label: 'Open orders', value: formatMoney(sum(open)), sub: `${open.length} orders` },
    { label: 'Completed', value: formatMoney(sum(completed)) },
    { label: 'Avg order', value: formatMoney(all.length ? sum(all) / all.length : 0) },
    { label: 'Problem rate', value: `${all.length ? Math.round((problems.length / all.length) * 100) : 0}%`, sub: `${problems.length} orders` },
  ];
  const volume = {
    title: 'Volume by status',
    total: formatMoney(sum(all)),
    parts: COLUMNS.map((col) => ({
      label: col.title,
      value: sum(all.filter((o) => col.statuses.includes(o.status))),
    })),
  };
  const maxCount = Math.max(1, ...COLUMNS.map((col) => visible.filter((o) => col.statuses.includes(o.status)).length));

  return (
    <div className="animate-in">
      <KpiStrip kpis={kpis} volume={volume} />

      <div className="toolbar">
        {PILLS.map((p) => (
          <Pill
            key={p.value}
            active={filter === p.value}
            count={p.statuses ? all.filter((o) => p.statuses.includes(o.status)).length : all.length}
            onClick={() => setFilter(p.value)}
          >
            {p.label}
          </Pill>
        ))}
        <div className="toolbar-spacer" />
        <span className="sort-label"><ArrowUpDown size={14} /> Newest first</span>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {view === 'board' ? (
        <div className="board">
          {COLUMNS.map((col) => {
            const items = visible.filter((o) => col.statuses.includes(o.status));
            return (
              <Column
                key={col.key}
                title={col.title}
                count={items.length}
                meta={<><strong>{formatMoney(sum(items))}</strong> · {items.length} order{items.length === 1 ? '' : 's'}</>}
                progress={(items.length / maxCount) * 100}
              >
                {items.map((o) => {
                  const c = customerById[o.customer_id];
                  const stale = o.status === 'processing' || o.status === 'pending' || o.status === 'on-hold'
                    ? daysSince(o.updated_at) : 0;
                  return (
                    <article key={o.id} className="deal-card" onClick={() => navigate(`/customers/${o.customer_id}`)}>
                      <div className="chips">
                        <span className="chip">#{o.woo_order_id}</span>
                        <span className={`status-badge ${o.status}`}>{o.status}</span>
                        {o.payment_method && <span className="chip">{o.payment_method}</span>}
                      </div>
                      <div className="deal-title">{itemsLabel(o)}</div>
                      <div className="deal-sub">
                        {c ? `${c.first_name} ${c.last_name}` : `Customer #${o.customer_id}`}
                        {c && <><span className="dot">·</span>{c.email}</>}
                      </div>
                      <div className="deal-foot">
                        <span className="deal-amount">{formatCurrency(o.total, o.currency)}</span>
                        {stale >= 3 ? <InactiveFlag days={stale} label="no update" /> : <CardDate date={o.created_at} />}
                        <Avatar text={c ? getInitials(c.first_name, c.last_name) : '?'} title={c?.email} />
                      </div>
                    </article>
                  );
                })}
              </Column>
            );
          })}
        </div>
      ) : (
        <div className="page-body">
          <table className="data-table">
            <thead>
              <tr><th>Order</th><th>Customer</th><th>Items</th><th>Status</th><th>Total</th><th>Date</th></tr>
            </thead>
            <tbody>
              {visible.map((o) => {
                const c = customerById[o.customer_id];
                return (
                  <tr key={o.id} className="clickable" onClick={() => navigate(`/customers/${o.customer_id}`)}>
                    <td style={{ fontWeight: 500 }}>#{o.woo_order_id}</td>
                    <td>{c ? `${c.first_name} ${c.last_name}` : `Customer #${o.customer_id}`}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>{itemsLabel(o)}</td>
                    <td><span className={`status-badge ${o.status}`}>{o.status}</span></td>
                    <td>{formatCurrency(o.total, o.currency)}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{formatDate(o.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
