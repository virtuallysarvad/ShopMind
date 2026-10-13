import { useEffect, useMemo, useState } from 'react';
import { Send } from 'lucide-react';
import { api } from '../api';
import { formatMoney, getSegmentInfo } from '../utils';
import { Drawer } from './board';

const TYPES = [
  { value: 'follow_up_email', label: 'Email' },
  { value: 'segment_change', label: 'Segment change' },
  { value: 'issue_alert', label: 'Order issue' },
];
const SEGMENTS = ['new', 'regular', 'vip', 'at_risk'];
const ISSUES = [
  { value: 'payment_failed', label: 'Payment failed' },
  { value: 'delayed_shipping', label: 'Delayed shipping' },
  { value: 'refund_requested', label: 'Refund requested' },
  { value: 'stuck_processing', label: 'Stuck in processing' },
  { value: 'other', label: 'Other' },
];

/**
 * "+ New proposal" form. A human adds a card by hand; it lands as Pending
 * and goes through the same approve → execute → WooCommerce write-back path.
 */
export default function NewProposal({ customers, onClose, onCreated }) {
  const [type, setType] = useState('follow_up_email');
  const [customerId, setCustomerId] = useState('');
  const [segment, setSegment] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [orderId, setOrderId] = useState('');
  const [issue, setIssue] = useState('payment_failed');
  const [note, setNote] = useState('');
  const [orders, setOrders] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const sorted = useMemo(
    () => [...(customers || [])].sort((a, b) => `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`)),
    [customers]
  );
  const customer = sorted.find((c) => String(c.id) === String(customerId));

  // Order issue: list the chosen customer's orders.
  useEffect(() => {
    setOrderId('');
    if (type !== 'issue_alert' || !customerId) { setOrders([]); return; }
    api.getOrders(customerId).then(setOrders).catch(() => setOrders([]));
  }, [type, customerId]);

  const ready = customerId && (
    (type === 'follow_up_email' && subject.trim() && body.trim())
    || (type === 'segment_change' && segment && segment !== customer?.segment)
    || (type === 'issue_alert' && orderId)
  );

  async function submit(e) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError('');
    const payload = { proposal_type: type, customer_id: Number(customerId), note: note.trim() || null };
    if (type === 'follow_up_email') Object.assign(payload, { subject: subject.trim(), body: body.trim() });
    if (type === 'segment_change') payload.new_segment = segment;
    if (type === 'issue_alert') Object.assign(payload, { woo_order_id: Number(orderId), issue_type: issue });
    try {
      onCreated(await api.createProposal(payload));
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <Drawer
      title="New proposal"
      onClose={onClose}
      footer={(
        <button className="btn btn-primary" form="new-proposal" type="submit" disabled={!ready || busy}>
          <Send size={15} /> {busy ? 'Adding...' : 'Add to inbox'}
        </button>
      )}
    >
      <form id="new-proposal" className="form" onSubmit={submit}>
        <div className="segmented">
          {TYPES.map((t) => (
            <button key={t.value} type="button" className={type === t.value ? 'active' : ''} onClick={() => setType(t.value)}>
              {t.label}
            </button>
          ))}
        </div>

        <label className="field">
          <span>Customer</span>
          <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            <option value="">Pick a customer</option>
            {sorted.map((c) => (
              <option key={c.id} value={c.id}>
                {`${c.first_name} ${c.last_name}`.trim() || c.email} · {getSegmentInfo(c.segment).label} · {formatMoney(c.total_spent)}
              </option>
            ))}
          </select>
        </label>

        {type === 'follow_up_email' && (
          <>
            <label className="field">
              <span>Subject</span>
              <input value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} placeholder="Your order is on its way" />
            </label>
            <label className="field">
              <span>Message</span>
              <textarea rows={7} value={body} maxLength={5000} onChange={(e) => setBody(e.target.value)}
                placeholder={customer ? `Hi ${customer.first_name},` : 'Hi,'} />
            </label>
          </>
        )}

        {type === 'segment_change' && (
          <label className="field">
            <span>Move to {customer && <em>(now {getSegmentInfo(customer.segment).label})</em>}</span>
            <select value={segment} onChange={(e) => setSegment(e.target.value)}>
              <option value="">Pick a segment</option>
              {SEGMENTS.map((s) => (
                <option key={s} value={s} disabled={s === customer?.segment}>{getSegmentInfo(s).label}</option>
              ))}
            </select>
          </label>
        )}

        {type === 'issue_alert' && (
          <>
            <label className="field">
              <span>Order</span>
              <select value={orderId} onChange={(e) => setOrderId(e.target.value)} disabled={!customerId}>
                <option value="">{customerId ? (orders.length ? 'Pick an order' : 'No orders for this customer') : 'Pick a customer first'}</option>
                {orders.map((o) => (
                  <option key={o.id} value={o.woo_order_id}>#{o.woo_order_id} · {o.status} · {formatMoney(o.total)}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Issue</span>
              <select value={issue} onChange={(e) => setIssue(e.target.value)}>
                {ISSUES.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
              </select>
            </label>
          </>
        )}

        <label className="field">
          <span>Why (optional)</span>
          <textarea rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)}
            placeholder="Shown as the card's summary" />
        </label>

        <p className="form-hint">It lands in Pending. Nothing changes until someone approves it.</p>
        {error && <p className="form-error">{error}</p>}
      </form>
    </Drawer>
  );
}
