import { useState, useEffect, useCallback } from 'react';

/**
 * Custom hook for fetching data with loading and error states.
 */
export function useApi(fetchFn, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchFn();
      setData(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}

/**
 * Format a date string for display.
 */
export function formatDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Format currency.
 */
export function formatCurrency(amount, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
  }).format(amount);
}

/**
 * Get segment display info.
 */
export function getSegmentInfo(segment) {
  const map = {
    new: { label: 'New', color: 'new', icon: '✨' },
    regular: { label: 'Regular', color: 'regular', icon: '👤' },
    vip: { label: 'VIP', color: 'vip', icon: '⭐' },
    at_risk: { label: 'At Risk', color: 'at_risk', icon: '⚠️' },
  };
  return map[segment] || { label: segment, color: 'new', icon: '?' };
}

/**
 * Get initials from a name.
 */
export function getInitials(firstName, lastName) {
  const f = (firstName || '?')[0].toUpperCase();
  const l = (lastName || '')[0]?.toUpperCase() || '';
  return f + l;
}

/**
 * Short card date: "Today, 2:00 PM" for today, otherwise "Mon, Oct 6".
 */
export function formatShortDate(dateStr) {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return `Today, ${d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
  }
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

export function isToday(dateStr) {
  return !!dateStr && new Date(dateStr).toDateString() === new Date().toDateString();
}

/** Whole days between a date and now (0 when missing). */
export function daysSince(dateStr) {
  if (!dateStr) return 0;
  return Math.max(0, Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000));
}

/** Compact currency for KPI tiles: $215,400 (no cents). */
export function formatMoney(amount, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency, maximumFractionDigits: 0,
  }).format(amount || 0);
}

/** Case-insensitive "does any of these fields contain the query". */
export function matchesQuery(query, ...fields) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return true;
  return fields.some((f) => String(f ?? '').toLowerCase().includes(q));
}

/** Pages fire this after approving/rejecting so the nav badge stays correct. */
export function notifyDataChanged() {
  window.dispatchEvent(new Event('shopmind:changed'));
}
