import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProviderLogo } from '../../../components/icons/ProviderLogos';

describe('ProviderLogo', () => {
  test('renders svg and path for known provider', () => {
    const { container } = render(<ProviderLogo provider="openai" />);
    const svg = container.querySelector('svg');
    const path = container.querySelector('path');

    expect(svg).toBeInTheDocument();
    expect(path).toBeInTheDocument();
    expect(path?.getAttribute('d')).toBeTruthy();
  });

  test('renders title and img role when title is provided', () => {
    render(<ProviderLogo provider="anthropic" title="Anthropic logo" />);

    const svg = screen.getByRole('img', { name: 'Anthropic logo' });
    expect(svg).toBeInTheDocument();
    expect(screen.getByText('Anthropic logo').tagName.toLowerCase()).toBe('title');
  });

  test('sets aria-hidden when no title is provided', () => {
    const { container } = render(<ProviderLogo provider="gemini" />);
    const svg = container.querySelector('svg');

    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });
});
