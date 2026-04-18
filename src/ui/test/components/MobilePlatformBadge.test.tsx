import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import MobilePlatformBadge from '../../components/MobilePlatformBadge';

describe('MobilePlatformBadge', () => {
  test('renders the compact badge for tab indicators', () => {
    render(<MobilePlatformBadge platform="telegram" />);

    const badge = screen.getByTitle('From Telegram');
    expect(badge).toHaveClass('mobile-platform-badge--small');
    expect(badge.querySelector('svg')).not.toBeNull();
  });

  test('renders the pill badge with a custom display name', () => {
    render(<MobilePlatformBadge platform="whatsapp" size="pill" displayName="Alex" />);

    expect(screen.getByText('via Alex')).toBeInTheDocument();
    expect(screen.getByText('via Alex').closest('.mobile-platform-badge')).toHaveClass(
      'mobile-platform-badge--pill',
    );
  });
});
