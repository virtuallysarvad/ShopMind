import { useState } from 'react';
import { Store, RefreshCw, CheckCircle2, CircleAlert, FlaskConical } from 'lucide-react';
import { api } from '../api';
import { useApi } from '../utils';

/** Dashboard card: which WooCommerce store is connected, and a Sync now button. */
export default function WooConnection({ onSynced }) {
  const { data: status, refetch } = useApi(() => api.wooStatus());
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const sync = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.wooSync();
      setResult({ ok: true, text: `Synced ${r.fetched} orders: ${r.new} new, ${r.updated} updated, ${r.proposals_from_agents} new proposals${r.errors?.length ? `, ${r.errors.length} errors` : ''}.` });
      window.dispatchEvent(new Event('shopmind:changed'));
      refetch();
      onSynced?.();
    } catch (e) {
      setResult({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const live = status?.mode === 'live';
  const connected = live && status?.connected;

  return (
    <div className="card woo-card">
      <div className="woo-head">
        <span className="woo-icon"><Store size={18} /></span>
        <div className="woo-text">
          <div className="card-title">WooCommerce</div>
          {!status && <span className="woo-sub">Checking connection...</span>}
          {status && !live && (
            <span className="woo-sub"><FlaskConical size={13} /> Demo data (mock store). Set SHOPMIND_WOO_MODE=live to connect a real store.</span>
          )}
          {live && connected && (
            <span className="woo-sub ok"><CheckCircle2 size={13} /> Connected to {status.store_url} · {status.total_orders} orders in store · write-back {status.writeback ? 'on' : 'off'}</span>
          )}
          {live && !connected && (
            <span className="woo-sub bad"><CircleAlert size={13} /> Can't reach {status.store_url}: {status.detail}</span>
          )}
        </div>
        {live && (
          <button className="btn btn-primary btn-sm" onClick={sync} disabled={busy || !connected}>
            <RefreshCw size={14} className={busy ? 'spin' : ''} /> {busy ? 'Syncing...' : 'Sync now'}
          </button>
        )}
      </div>
      {result && <div className={`woo-result ${result.ok ? 'ok' : 'bad'}`}>{result.text}</div>}
    </div>
  );
}
