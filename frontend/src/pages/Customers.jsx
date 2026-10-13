import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpDown } from 'lucide-react';
import { api } from '../api';
import {
  useApi, formatMoney, getSegmentInfo, getInitials, daysSince, matchesQuery,
} from '../utils';
import {
  KpiStrip, Pill, ViewToggle, Column, Avatar, CardDate, InactiveFlag,
  Loading, ErrorBox, useSearch,
} from '../components/board';

// Segments are decided by deterministic rules (classify_customer), so this
// board is read-only: no dragging customers between segments by hand.
const SEGMENTS = ['new', 'regular', 'vip', 'at_risk'];

export default function Customers() {
  const { query } = useSearch();
  const navigate = useNavigate();
  const [segmentFilter, setSegmentFilter] = useState('');
  const [view, setView] = useState('board');

  const { data: customers, loading, error } = useApi(() => api.getCustomers());
  const { data: orders } = useApi(() => api.getOrders());
  const { data: proposals } = useApi(() => api.getProposals('pending'));

  // Last order date and pending-proposal count per customer, derived client-side.
  const lastOrder = useMemo(() => {
    const m = {};
    for (const o of orders || []) {
      if (!m[o.customer_id] || new Date(o.created_at) > new Date(m[o.customer_id])) m[o.customer_id] = o.created_at;
    }
    return m;
  }, [orders]);
  const pendingFor = useMemo(() => {
    const m = {};
    for (const p of proposals || []) m[p.customer_id] = (m[p.customer_id] || 0) + 1;
    return m;
  }, [proposals]);

  if (loading && !customers) return <Loading />;
  if (error) return <ErrorBox message={error} />;

  const all = customers || [];
  const visible = all.filter((c) =>
    matchesQuery(query, c.first_name, c.last_name, `${c.first_name} ${c.last_name}`, c.email)
  );
  const bySeg = (seg) => visible.filter((c) => c.segment === seg);

  const revenue = all.reduce((s, c) => s + c.total_spent, 0);
  const vip = all.filter((c) => c.segment === 'vip');
  const atRisk = all.filter((c) => c.segment === 'at_risk');

  const kpis = [
    { label: 'Customers', value: all.length, sub: `${atRisk.length} at risk` },
    { label: 'Lifetime revenue', value: formatMoney(revenue) },
    { label: 'Avg spend', value: formatMoney(all.length ? revenue / all.length : 0) },
    { label: 'VIP share', value: `${all.length ? Math.round((vip.length / all.length) * 100) : 0}%`, sub: `${vip.length} VIPs` },
  ];
  const volume = {
    title: 'Revenue by segment',
    total: formatMoney(revenue),
    parts: SEGMENTS.map((seg) => ({
      label: getSegmentInfo(seg).label,
      value: all.filter((c) => c.segment === seg).reduce((s, c) => s + c.total_spent, 0),
    })),
  };

  const columns = segmentFilter ? [segmentFilter] : SEGMENTS;
  const maxCount = Math.max(1, ...SEGMENTS.map((s) => bySeg(s).length));

  return (
    <div className="animate-in">
      <KpiStrip kpis={kpis} volume={volume} />

      <div className="toolbar">
        <Pill active={!segmentFilter} count={all.length} onClick={() => setSegmentFilter('')}>All</Pill>
        {SEGMENTS.map((seg) => (
          <Pill
            key={seg}
            active={segmentFilter === seg}
            count={all.filter((c) => c.segment === seg).length}
            onClick={() => setSegmentFilter(seg)}
          >
            {getSegmentInfo(seg).label}
          </Pill>
        ))}
        <div className="toolbar-spacer" />
        <span className="sort-label"><ArrowUpDown size={14} /> Highest spend</span>
        <ViewToggle view={view} onChange={setView} />
      </div>

      {view === 'board' ? (
        <div className="board">
          {columns.map((seg) => {
            const items = bySeg(seg).sort((a, b) => b.total_spent - a.total_spent);
            const value = items.reduce((s, c) => s + c.total_spent, 0);
            const orderCount = items.reduce((s, c) => s + c.order_count, 0);
            return (
              <Column
                key={seg}
                title={getSegmentInfo(seg).label}
                count={items.length}
                meta={<><strong>{formatMoney(value)}</strong> · {orderCount} orders</>}
                progress={(items.length / maxCount) * 100}
                empty="No customers in this segment"
              >
                {items.map((c) => {
                  const last = lastOrder[c.id];
                  const idle = daysSince(last);
                  return (
                    <article key={c.id} className="deal-card" onClick={() => navigate(`/customers/${c.id}`)}>
                      <div className="chips">
                        <span className="chip">{c.order_count} order{c.order_count === 1 ? '' : 's'}</span>
                        {pendingFor[c.id] > 0 && (
                          <span className="chip accent">{pendingFor[c.id]} pending</span>
                        )}
                      </div>
                      <div className="deal-title">{c.first_name} {c.last_name}</div>
                      <div className="deal-sub">{c.email}</div>
                      <div className="deal-foot">
                        <span className="deal-amount">{formatMoney(c.total_spent)}</span>
                        {seg === 'at_risk' && idle > 0
                          ? <InactiveFlag days={idle} />
                          : last ? <CardDate date={last} /> : null}
                        <Avatar text={getInitials(c.first_name, c.last_name)} title={c.email} />
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
              <tr><th>Customer</th><th>Email</th><th>Segment</th><th>Orders</th><th>Total spent</th></tr>
            </thead>
            <tbody>
              {visible
                .filter((c) => !segmentFilter || c.segment === segmentFilter)
                .map((c) => {
                  const seg = getSegmentInfo(c.segment);
                  return (
                    <tr key={c.id} className="clickable" onClick={() => navigate(`/customers/${c.id}`)}>
                      <td style={{ fontWeight: 500 }}>{c.first_name} {c.last_name}</td>
                      <td style={{ color: 'var(--text-secondary)' }}>{c.email}</td>
                      <td><span className={`segment-badge ${seg.color}`}>{seg.label}</span></td>
                      <td>{c.order_count}</td>
                      <td>{formatMoney(c.total_spent)}</td>
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
