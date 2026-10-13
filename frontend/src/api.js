/**
 * API client for ShopMind backend.
 */

// Override with VITE_API_BASE (e.g. in frontend/.env.local); defaults to the local backend.
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Dashboard
  getDashboard: () => request('/api/dashboard'),

  // Customers
  getCustomers: (segment, limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (segment) params.set('segment', segment);
    return request(`/api/customers?${params}`);
  },
  getCustomer: (id) => request(`/api/customers/${id}`),

  // Orders
  getOrders: (customerId, limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (customerId) params.set('customer_id', String(customerId));
    return request(`/api/orders?${params}`);
  },
  getOrder: (id) => request(`/api/orders/${id}`),

  // Timeline
  getTimeline: (customerId) => request(`/api/customers/${customerId}/timeline`),

  // Proposals
  getProposals: (status, limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set('status', status);
    return request(`/api/proposals?${params}`);
  },
  getProposal: (id) => request(`/api/proposals/${id}`),
  reviewProposal: (id, action, reviewedBy = 'admin') =>
    request(`/api/proposals/${id}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, reviewed_by: reviewedBy }),
    }),

  // Webhook (for demo/testing)
  sendTestOrder: (payload) =>
    request('/webhooks/woocommerce/order', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Health
  health: () => request('/health'),
};
