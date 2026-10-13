import { useEffect, useRef, useState, useCallback } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { LayoutDashboard, Users, ShoppingCart, Inbox, Brain, Search, Sparkles } from 'lucide-react';
import { api } from './api';
import { useApi } from './utils';
import { SearchContext } from './components/board';
import Dashboard from './pages/Dashboard';
import Customers from './pages/Customers';
import CustomerDetail from './pages/CustomerDetail';
import Orders from './pages/Orders';
import Proposals from './pages/Proposals';

import './App.css';

function TopBar({ query, setQuery }) {
  const { data: dashboard, refetch } = useApi(() => api.getDashboard());
  const pendingCount = dashboard?.pending_proposals || 0;
  const inputRef = useRef(null);

  useEffect(() => {
    window.addEventListener('shopmind:changed', refetch);
    return () => window.removeEventListener('shopmind:changed', refetch);
  }, [refetch]);

  // "/" focuses search, like the design.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const link = ({ isActive }) => `nav-link ${isActive ? 'active' : ''}`;

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <span className="topbar-brand-icon"><Brain size={16} /></span>
        ShopMind
      </div>
      <nav className="topbar-nav">
        <NavLink to="/" end className={link}><LayoutDashboard size={16} /> Dashboard</NavLink>
        <NavLink to="/proposals" className={link}>
          <Inbox size={16} /> Approvals
          {pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}
        </NavLink>
        <NavLink to="/customers" className={link}><Users size={16} /> Customers</NavLink>
        <NavLink to="/orders" className={link}><ShoppingCart size={16} /> Orders</NavLink>
      </nav>
      <div className="topbar-spacer" />
      <label className="search-box">
        <Search size={15} />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search customers, orders, proposals..."
        />
        <span className="kbd">/</span>
      </label>
    </header>
  );
}

/** Bottom-right pill: which LLM writes the text, and whether it answers. */
function LlmStatus() {
  const { data: health } = useApi(() => api.health());
  const provider = health?.llm_provider ?? 'fake';
  const down =
    (provider === 'lmstudio' && health?.lmstudio_reachable === false) ||
    (provider === 'ollama' && health?.ollama_reachable === false);

  let label = 'Connecting...';
  if (health) {
    if (provider === 'lmstudio') {
      const model = health.lmstudio_models?.[0];
      label = down ? 'LM Studio unreachable, using templates' : `LM Studio${model ? ` · ${model}` : ''}`;
    } else if (provider === 'ollama') {
      label = down ? 'Ollama unreachable, using templates' : 'Ollama · local model';
    } else {
      label = 'FakeLLM · rule-based templates';
    }
  }

  return (
    <div className="status-pill" title="Rules make every decision; the LLM only writes the text.">
      <span className={`status-dot ${down || !health ? 'down' : ''}`} />
      <Sparkles size={13} /> {label}
    </div>
  );
}

function App() {
  const [query, setQuery] = useState('');
  const setQ = useCallback((q) => setQuery(q), []);

  return (
    <BrowserRouter>
      <SearchContext.Provider value={{ query, setQuery: setQ }}>
        <div className="app-layout">
          <div className="app-panel">
            <TopBar query={query} setQuery={setQ} />
            <main className="main-content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/proposals" element={<Proposals />} />
                <Route path="/customers" element={<Customers />} />
                <Route path="/customers/:id" element={<CustomerDetail />} />
                <Route path="/orders" element={<Orders />} />
              </Routes>
            </main>
          </div>
          <LlmStatus />
        </div>
      </SearchContext.Provider>
    </BrowserRouter>
  );
}

export default App;
