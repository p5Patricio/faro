import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Gauge } from './Gauge.tsx';

describe('Gauge', () => {
  it('shows N/D and no meter value when the value is missing', () => {
    render(<Gauge value={null} label="Confianza" />);
    expect(screen.getByText('N/D')).toBeInTheDocument();
    expect(screen.getByRole('meter')).not.toHaveAttribute('aria-valuenow');
  });

  it('renders the percentage and exposes it on the meter role', () => {
    render(<Gauge value={0.35} label="Confianza" />);
    expect(screen.getByText('35%')).toBeInTheDocument();
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', '35');
  });

  it('flags "por debajo" when the value is under the threshold', () => {
    render(<Gauge value={0.35} threshold={0.6} label="Confianza" />);
    expect(screen.getByText(/Umbral para operar: 60%/)).toHaveTextContent('por debajo');
  });

  it('does not flag "por debajo" when at or above the threshold', () => {
    render(<Gauge value={0.7} threshold={0.6} label="Confianza" />);
    expect(screen.getByText(/Umbral para operar: 60%/)).not.toHaveTextContent('por debajo');
  });
});
