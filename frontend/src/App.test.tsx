import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { App } from './App';

describe('App shell', () => {
  it('renders the planner panel, map region and labelled legend', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /weather-aware truck routing/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /route map/i })).toBeInTheDocument();
    const legend = screen.getByRole('list', { name: /risk levels/i });
    for (const label of ['Low', 'Moderate', 'High', 'Severe', 'No Travel', 'No forecast']) {
      expect(legend).toHaveTextContent(label);
    }
  });

});
