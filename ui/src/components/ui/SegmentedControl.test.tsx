import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SegmentedControl } from './SegmentedControl.tsx';

const OPTIONS = [
  { value: 'a', label: 'Uno' },
  { value: 'b', label: 'Dos' },
  { value: 'c', label: 'Tres' },
] as const;

describe('SegmentedControl', () => {
  it('marks the active tab with aria-selected and roving tabindex', () => {
    render(<SegmentedControl label="Secciones" options={[...OPTIONS]} value="b" onChange={() => {}} />);

    expect(screen.getByRole('tab', { name: 'Dos' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Uno' })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tab', { name: 'Dos' })).toHaveAttribute('tabindex', '0');
  });

  it('calls onChange when a tab is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<SegmentedControl label="Secciones" options={[...OPTIONS]} value="a" onChange={onChange} />);

    await user.click(screen.getByRole('tab', { name: 'Tres' }));
    expect(onChange).toHaveBeenCalledWith('c');
  });

  it('moves with arrow keys and wraps around', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<SegmentedControl label="Secciones" options={[...OPTIONS]} value="c" onChange={onChange} />);

    screen.getByRole('tab', { name: 'Tres' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(onChange).toHaveBeenCalledWith('a'); // wrapped past the end
  });

  it('links tabs to panels when idPrefix is given', () => {
    render(
      <SegmentedControl label="Secciones" idPrefix="x" options={[...OPTIONS]} value="a" onChange={() => {}} />,
    );
    const tab = screen.getByRole('tab', { name: 'Uno' });
    expect(tab).toHaveAttribute('id', 'x-tab-a');
    expect(tab).toHaveAttribute('aria-controls', 'x-panel-a');
  });
});
