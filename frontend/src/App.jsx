import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Users, ShoppingCart, Inbox, Brain,
} from 'lucide-react';
import { api } from './api';
import { useApi } from './utils';
import Dashboard from './pages/Dashboard';
import Customers from './pages/Customers';
import CustomerDetail from './pages/CustomerDetail';
import Orders from './pages/Orders';
import Proposals from './pages/Proposals';

import './App.css';

function Sidebar() {
  const { data: dashboard } = useApi(() => api.getDashboard());
  const { data: health } = useApi(() => api.health());
  const pendingCount = dashboard?.pending_proposals || 0;

  // Active LLM provider comes from the backend so the footer never lies about
  // rule-based (FakeLLM) vs. real (Ollama / LM Studio) output.
  const provider = health?.llm_provider ?? 'fake';
  const lmstudioDown =
    provider === 'lmstudio' && health?.lmstudio_reachable === false;
  const ollamaDown = provider === 'ollama' && health?.ollama_reachable === false;
  const llmLabel =
    provider === 'lmstudio'
      ? (lmstudioDown
          ? 'LM Studio • Local Model (unreachable)'
          : 'LM Studio • Local Model')
    : ollamaDown
      ? 'Ollama • Local Model (unreachable)'
      : provider === 'ollama'
        ? 'Ollama • Local Model'
        : 'FakeLLM Active • Rule-Based';
  const dotDown = lmstudioDown || ollamaDown;

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">
          <Brain size={22} color="white" />
        </div>
        <div>
          <h1>ShopMind</h1>
          <span>AI-Powered CRM</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <LayoutDashboard size={18} />
          <span>Dashboard</span>
        </NavLink>
        <NavLink to="/customers" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Users size={18} />
          <span>Customers</span>
        </NavLink>
        <NavLink to="/orders" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <ShoppingCart size={18} />
          <span>Orders</span>
        </NavLink>
        <NavLink to="/proposals" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Inbox size={18} />
          <span>Approval Inbox</span>
          {pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}
        </NavLink>
      </nav>

      <div style={{
        padding: '16px 12px',
        borderTop: '1px solid var(--border)',
        marginTop: 'auto',
        fontSize: '0.72rem',
        color: 'var(--text-muted)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
          <div style={{
            width: '8px', height: '8px', borderRadius: '50%',
            background: dotDown ? 'var(--warning)' : 'var(--success)',
            boxShadow: `0 0 6px ${dotDown ? 'var(--warning)' : 'var(--success)'}`,
          }} />
          {health ? (dotDown ? 'LLM Offline' : 'System Online') : 'Connecting...'}
        </div>
        <div>{llmLabel}</div>
      </div>
    </aside>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/customers/:id" element={<CustomerDetail />} />
            <Route path="/orders" element={<Orders />} />
            <Route path="/proposals" element={<Proposals />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
