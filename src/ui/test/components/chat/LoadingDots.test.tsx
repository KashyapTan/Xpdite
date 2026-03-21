import { describe, expect, test } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { LoadingDots } from '../../../components/chat/LoadingDots';

describe('LoadingDots', () => {
  test('is visible by default', () => {
    const { container } = render(<LoadingDots />);
    expect(container.querySelector('.thinking-animation-container')).toBeInTheDocument();
  });

  test('is hidden when isVisible is false', () => {
    const { container } = render(<LoadingDots isVisible={false} />);
    expect(container.firstChild).toBeNull();
  });

  test('applies fade-out class when transitioning to hidden', () => {
    const { container, rerender } = render(<LoadingDots isVisible={true} />);
    rerender(<LoadingDots isVisible={false} />);

    const root = container.querySelector('.thinking-animation-container');
    expect(root).toBeInTheDocument();
    expect(root).toHaveClass('fade-out');
  });

  test('stays mounted when animation ends while visible', () => {
    const { container } = render(<LoadingDots isVisible={true} />);

    const root = container.querySelector('.thinking-animation-container');
    expect(root).toBeInTheDocument();
    fireEvent.animationEnd(root!);

    expect(container.firstChild).toBeInTheDocument();
  });

  test('keeps fade-out class after animation event when hidden', () => {
    const { container, rerender } = render(<LoadingDots isVisible={true} />);
    rerender(<LoadingDots isVisible={false} />);

    const root = container.querySelector('.thinking-animation-container');
    expect(root).toBeInTheDocument();
    fireEvent.animationEnd(root!);

    expect(container.querySelector('.thinking-animation-container')).toHaveClass('fade-out');
  });

  test('contains expected animated structure', () => {
    const { container } = render(<LoadingDots />);
    expect(container.querySelector('.black-hole-wrapper')).toBeInTheDocument();
    expect(container.querySelector('.gravitational-lens')).toBeInTheDocument();
    expect(container.querySelector('.accretion-disk')).toBeInTheDocument();
    expect(container.querySelector('.event-horizon')).toBeInTheDocument();
    expect(container.querySelector('.black-hole-core')).toBeInTheDocument();
  });
});
