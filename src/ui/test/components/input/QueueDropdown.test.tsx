import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { QueueDropdown } from '../../../components/input/QueueDropdown';

describe('QueueDropdown', () => {
  const items = [
    { item_id: '1', preview: 'First queued query', position: 1 },
    { item_id: '2', preview: 'Second queued query', position: 2 },
  ];

  test('returns null for empty queue', () => {
    const { container } = render(<QueueDropdown items={[]} onCancel={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders collapsed header with next item preview', () => {
    render(<QueueDropdown items={items} onCancel={vi.fn()} />);

    expect(screen.getByText('Queued next')).toBeInTheDocument();
    expect(screen.getByText('First queued query')).toBeInTheDocument();
    expect(screen.queryByText('Second queued query')).not.toBeInTheDocument();
  });

  test('expands to show all queued items and allows cancel', () => {
    const onCancel = vi.fn();
    render(<QueueDropdown items={items} onCancel={onCancel} />);

    fireEvent.click(screen.getByRole('button', { name: 'Expand queued messages' }));
    expect(screen.getByRole('button', { name: 'Collapse queued messages' })).toBeInTheDocument();
    expect(screen.getByText('Second queued query')).toBeInTheDocument();

    const cancelButtons = screen.getAllByRole('button', { name: 'Cancel this queued message' });
    fireEvent.click(cancelButtons[1]);
    expect(onCancel).toHaveBeenCalledWith('2');
  });
});

