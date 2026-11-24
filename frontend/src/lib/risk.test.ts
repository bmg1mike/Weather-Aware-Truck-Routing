import { describe, expect, it } from 'vitest';

import { levelFromIndex, RISK_LEVELS, RISK_STYLES } from './risk';

describe('risk palette', () => {
  it('gives every level, including unknown, a distinct colour and a text label', () => {
    const keys = [...RISK_LEVELS, 'unknown'] as const;
    const colours = keys.map((k) => RISK_STYLES[k].colour.toLowerCase());
    expect(new Set(colours).size).toBe(keys.length);
    for (const k of keys) expect(RISK_STYLES[k].label).not.toHaveLength(0);
  });

  it('maps backend numeric levels 0-4 in order, and null to unknown, never to low', () => {
    expect([0, 1, 2, 3, 4].map(levelFromIndex)).toEqual(['low', 'moderate', 'high', 'severe', 'no_travel']);
    expect(levelFromIndex(null)).toBe('unknown');
    expect(levelFromIndex(7)).toBe('unknown');
  });
});
