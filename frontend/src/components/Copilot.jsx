import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Bot, SendHorizontal, Wrench, X, Sparkles, Inbox, RotateCcw } from 'lucide-react';
import { api } from '../api';

/**
 * Shop Copilot: a chat agent over the CRM.  The conversation lives in a
 * context so the full page (/copilot) and the floating drawer share it.
 */

const SUGGESTIONS = [
  'How is my shop doing?',
  'Who are my top customers?',
  'Show failed orders',
  'What is waiting for approval?',
  'Draft a thank-you email to Alice',
  'Make David VIP',
];

const TOOL_LABELS = {
  shop_stats: 'Read shop stats',
  search_customers: 'Searched customers',
  get_customer: 'Opened customer',
  list_orders: 'Listed orders',
  list_pending_proposals: 'Checked Approval Inbox',
  propose_segment_change: 'Proposed segment change',
  draft_follow_up_email: 'Drafted email',
  flag_order_issue: 'Flagged order',
};

const CopilotContext = createContext(null);
export const useCopilot = () => useContext(CopilotContext);

export function CopilotProvider({ children }) {
  const [messages, setMessages] = useState([]); // {role, content, steps?, mode?, model?, note?, proposals?}
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const send = useCallback(async (text) => {
    const content = text.trim();
    if (!content || busy) return;
    const next = [...messages, { role: 'user', content }];
    setMessages(next);
    setBusy(true);
    try {
      const res = await api.copilotChat(next.map(({ role, content: c }) => ({ role, content: c })));
      setMessages((m) => [...m, {
        role: 'assistant', content: res.reply, steps: res.steps, mode: res.mode,
        model: res.model, note: res.note, proposals: res.proposals_created,
      }]);
      if (res.proposals_created?.length) window.dispatchEvent(new Event('shopmind:changed'));
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', content: `Something went wrong: ${e.message}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }, [messages, busy]);

  const reset = useCallback(() => setMessages([]), []);

  return (
    <CopilotContext.Provider value={{ messages, busy, send, reset, open, setOpen }}>
      {children}
    </CopilotContext.Provider>
  );
}

function Steps({ steps }) {
  const [show, setShow] = useState(false);
  if (!steps?.length) return null;
  return (
    <div className="cp-steps">
      <button className="cp-steps-toggle" onClick={() => setShow((s) => !s)}>
        <Wrench size={12} /> {steps.length} tool call{steps.length === 1 ? '' : 's'}
        {steps.some((s) => s.writes) && <span className="chip accent">needs approval</span>}
      </button>
      {show && (
        <ul>
          {steps.map((s, i) => (
            <li key={i}>
              <strong>{TOOL_LABELS[s.tool] || s.tool}</strong>
              <code>{JSON.stringify(s.args)}</code>
              {s.result?.error && <span className="cp-err"> {s.result.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Message({ m, onNavigate }) {
  if (m.role === 'user') return <div className="cp-msg cp-user">{m.content}</div>;
  return (
    <div className={`cp-msg cp-bot ${m.error ? 'cp-error' : ''}`}>
      <div className="cp-bot-head">
        <Bot size={14} />
        <span>{m.mode === 'llm' ? (m.model || 'Local LLM') : 'Built-in rules'}</span>
      </div>
      <div className="cp-text">{m.content}</div>
      {m.note && <div className="cp-note">{m.note}</div>}
      {m.proposals?.length > 0 && (
        <Link
          to={`/proposals?open=${m.proposals[m.proposals.length - 1]}`}
          className="btn btn-sm btn-outline cp-inbox"
          onClick={onNavigate}
        >
          <Inbox size={13} /> Review {m.proposals.length === 1 ? `#${m.proposals[0]}` : `${m.proposals.length} proposals`} in Approval Inbox
        </Link>
      )}
      <Steps steps={m.steps} />
    </div>
  );
}

export function CopilotChat({ compact = false, onNavigate }) {
  const { messages, busy, send, reset } = useCopilot();
  const [text, setText] = useState('');
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, busy]);

  const submit = (e) => {
    e.preventDefault();
    send(text);
    setText('');
  };

  return (
    <div className={`cp ${compact ? 'cp-compact' : ''}`}>
      <div className="cp-log">
        {messages.length === 0 && (
          <div className="cp-empty">
            <Sparkles size={22} />
            <p>Ask about customers, orders and revenue. Anything that changes data goes to your Approval Inbox first.</p>
            <div className="cp-suggest">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => <Message key={i} m={m} onNavigate={onNavigate} />)}
        {busy && <div className="cp-msg cp-bot cp-typing"><span /><span /><span /></div>}
        <div ref={endRef} />
      </div>
      <form className="cp-input" onSubmit={submit}>
        {messages.length > 0 && (
          <button type="button" className="icon-btn" title="New chat" onClick={reset}><RotateCcw size={16} /></button>
        )}
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Ask your shop anything..."
          disabled={busy}
        />
        <button className="btn btn-primary btn-sm" disabled={busy || !text.trim()} aria-label="Send">
          <SendHorizontal size={15} />
        </button>
      </form>
    </div>
  );
}

/** Floating button + slide-out panel, available on every page. */
export function CopilotLauncher() {
  const { open, setOpen } = useCopilot();
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setOpen]);

  return (
    <>
      {!open && (
        <button className="cp-fab" onClick={() => setOpen(true)} title="Ask Copilot">
          <Bot size={18} /> Ask Copilot
        </button>
      )}
      {open && (
        <aside className="cp-panel" role="dialog" aria-label="Shop Copilot">
          <div className="cp-panel-head">
            <Bot size={16} /> <strong>Shop Copilot</strong>
            <span className="topbar-spacer" />
            <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Close"><X size={18} /></button>
          </div>
          <CopilotChat compact onNavigate={() => setOpen(false)} />
        </aside>
      )}
    </>
  );
}

export default function CopilotPage() {
  return (
    <div className="animate-in page-body">
      <div className="page-header">
        <h2>Shop Copilot</h2>
        <p>Your AI agent for the store. It reads your CRM with tools and proposes actions for you to approve.</p>
      </div>
      <div className="card cp-page-card"><CopilotChat /></div>
    </div>
  );
}
