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
