import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { EmptyState } from './EmptyState.tsx';

describe('EmptyState', () => {
  it('renders the title and hint', () => {
    render(<EmptyState title="Sin backtests" hint="Corré el job" />);
    expect(screen.getByText('Sin backtests')).toBeInTheDocument();
    expect(screen.getByText('Corré el job')).toBeInTheDocument();
  });

  it('copies the command to the clipboard when the chip is clicked', async () => {
    // userEvent.setup() installs a working clipboard stub in jsdom.
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText');

    render(<EmptyState title="x" command="py -m foo --bar" />);
    await user.click(screen.getByRole('button', { name: /copiar comando/i }));

    expect(writeText).toHaveBeenCalledWith('py -m foo --bar');
    expect(await screen.findByText('Copiado')).toBeInTheDocument();
    writeText.mockRestore();
  });

  it('shows a retry affordance in the error variant', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();

    render(<EmptyState title="Falló" variant="error" onRetry={onRetry} />);
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(onRetry).toHaveBeenCalledOnce();
  });
});
