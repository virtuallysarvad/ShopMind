/**
 * API client for ShopMind backend.
 */

const API_BASE = 'http://localhost:8000';

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
  getCustomers: (segment) => {
    const params = segment ? `?segment=${segment}` : '';
    return request(`/api/customers${params}`);
  },
  getCustomer: (id) => request(`/api/customers/${id}`),

  // Orders
  getOrders: (customerId) => {
    const params = customerId ? `?customer_id=${customerId}` : '';
    return request(`/api/orders${params}`);
  },
  getOrder: (id) => request(`/api/orders/${id}`),

  // Timeline
  getTimeline: (customerId) => request(`/api/customers/${customerId}/timeline`),

  // Proposals
  getProposals: (status) => {
    const params = status ? `?status=${status}` : '';
    return request(`/api/proposals${params}`);
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
