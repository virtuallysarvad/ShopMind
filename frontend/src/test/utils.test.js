import { describe, it, expect, vi } from 'vitest';
import {
  formatMoney, formatCurrency, getInitials, getSegmentInfo, matchesQuery, daysSince, notifyDataChanged,
} from '../utils';

describe('money in rupees', () => {
  it('uses Indian digit grouping', () => {
    expect(formatMoney(215400)).toBe('₹2,15,400');
    expect(formatCurrency(1234.5)).toBe('₹1,234.50');
  });
  it('treats missing amounts as zero', () => {
    expect(formatMoney(null)).toBe('₹0');
  });
});

describe('helpers', () => {
  it('builds initials', () => {
    expect(getInitials('alice', 'johnson')).toBe('AJ');
    expect(getInitials('', '')).toBe('?');
  });
  it('maps segments to labels', () => {
    expect(getSegmentInfo('at_risk').label).toBe('At Risk');
    expect(getSegmentInfo('unknown').label).toBe('unknown');
  });
  it('matches search across fields, case-insensitive', () => {
    expect(matchesQuery('ALICE', 'Re-segment', 'alice@example.com')).toBe(true);
    expect(matchesQuery('zzz', 'a', null)).toBe(false);
    expect(matchesQuery('   ', 'anything')).toBe(true);
  });
  it('counts whole days since a date', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 86400000 - 1000).toISOString();
    expect(daysSince(threeDaysAgo)).toBe(3);
    expect(daysSince(null)).toBe(0);
  });
  it('broadcasts data changes so every board refetches', () => {
    const spy = vi.fn();
    window.addEventListener('shopmind:changed', spy);
    notifyDataChanged();
    expect(spy).toHaveBeenCalledOnce();
    window.removeEventListener('shopmind:changed', spy);
  });
});
