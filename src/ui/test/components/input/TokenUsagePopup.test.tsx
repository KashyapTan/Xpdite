/**
 * Tests for TokenUsagePopup component.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TokenUsagePopup } from '../../../components/input/TokenUsagePopup';
import type { TokenUsage } from '../../../types';

describe('TokenUsagePopup', () => {
  const defaultTokenUsage: TokenUsage = {
    total: 50000,
    input: 30000,
    output: 20000,
    limit: 100000,
  };

  const defaultProps = {
    tokenUsage: defaultTokenUsage,
    show: false,
    onMouseEnter: vi.fn(),
    onMouseLeave: vi.fn(),
    onClick: vi.fn(),
    contextWindowIcon: '/icons/context-window.svg',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('icon rendering', () => {
    test('renders context window icon', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const icon = screen.getByAltText('Context Window Insights');
      expect(icon).toBeInTheDocument();
      expect(icon).toHaveAttribute('src', '/icons/context-window.svg');
    });

    test('icon has correct title attribute', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const icon = screen.getByAltText('Context Window Insights');
      expect(icon).toHaveAttribute('title', 'Context Window Insights');
    });

    test('icon has correct CSS class', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const icon = screen.getByAltText('Context Window Insights');
      expect(icon).toHaveClass('context-window-insights-svg');
    });
  });

  describe('popup visibility', () => {
    test('popup is hidden when show is false', () => {
      render(<TokenUsagePopup {...defaultProps} show={false} />);

      expect(screen.queryByText('Context Window')).not.toBeInTheDocument();
    });

    test('popup is visible when show is true', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      expect(screen.getByText('Context Window')).toBeInTheDocument();
    });
  });

  describe('token count display', () => {
    test('displays total tokens with formatting', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      expect(screen.getByText('Total Tokens')).toBeInTheDocument();
      expect(screen.getByText('50,000 (50%)')).toBeInTheDocument();
    });

    test('displays input tokens with formatting', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      expect(screen.getByText('Input Tokens')).toBeInTheDocument();
      expect(screen.getByText('30,000 (60%)')).toBeInTheDocument();
    });

    test('displays output tokens with formatting', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      expect(screen.getByText('Output Tokens')).toBeInTheDocument();
      expect(screen.getByText('20,000 (40%)')).toBeInTheDocument();
    });

    test('displays header with token summary', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      expect(screen.getByText('50,000 / 100,000 tokens • 50%')).toBeInTheDocument();
    });
  });

  describe('progress bar', () => {
    test('renders progress bar container', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      const progressContainer = document.querySelector('.token-progress-bar-container');
      expect(progressContainer).toBeInTheDocument();
    });

    test('progress bar fill has correct width based on percentage', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      const progressFill = document.querySelector('.token-progress-bar-fill');
      expect(progressFill).toHaveStyle({ width: '50%' });
    });

    test('progress bar is capped at 100% when usage exceeds limit', () => {
      const overLimitUsage: TokenUsage = {
        total: 120000,
        input: 80000,
        output: 40000,
        limit: 100000,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={overLimitUsage} show={true} />
      );

      const progressFill = document.querySelector('.token-progress-bar-fill');
      expect(progressFill).toHaveStyle({ width: '100%' });
    });
  });

  describe('percentage calculations', () => {
    test('calculates context window percentage correctly', () => {
      const tokenUsage: TokenUsage = {
        total: 25000,
        input: 15000,
        output: 10000,
        limit: 100000,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={tokenUsage} show={true} />
      );

      expect(screen.getByText('25,000 / 100,000 tokens • 25%')).toBeInTheDocument();
    });

    test('handles zero total tokens gracefully', () => {
      const zeroUsage: TokenUsage = {
        total: 0,
        input: 0,
        output: 0,
        limit: 100000,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={zeroUsage} show={true} />
      );

      expect(screen.getByText('0 / 100,000 tokens • 0%')).toBeInTheDocument();
      // Input and output percentages should show 0% when total is 0
      expect(screen.getAllByText('0 (0%)').length).toBeGreaterThanOrEqual(1);
    });

    test('handles unknown model context limit gracefully', () => {
      const unknownLimitUsage: TokenUsage = {
        total: 12345,
        input: 10000,
        output: 2345,
        limit: 0,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={unknownLimitUsage} show={true} />
      );

      expect(screen.getByText('12,345 / Unknown limit')).toBeInTheDocument();
      expect(screen.getByText('12,345')).toBeInTheDocument();

      const progressFill = document.querySelector('.token-progress-bar-fill');
      expect(progressFill).toHaveStyle({ width: '0%' });
    });

    test('rounds percentages to nearest integer', () => {
      const tokenUsage: TokenUsage = {
        total: 33333,
        input: 20000,
        output: 13333,
        limit: 100000,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={tokenUsage} show={true} />
      );

      // 33.333% should round to 33%
      expect(screen.getByText('33,333 / 100,000 tokens • 33%')).toBeInTheDocument();
    });
  });

  describe('mouse interactions', () => {
    test('calls onMouseEnter when hovering over container', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const container = document.querySelector('.context-window-insights-icon');
      fireEvent.mouseEnter(container!);

      expect(defaultProps.onMouseEnter).toHaveBeenCalledTimes(1);
    });

    test('calls onMouseLeave when mouse leaves container', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const container = document.querySelector('.context-window-insights-icon');
      fireEvent.mouseLeave(container!);

      expect(defaultProps.onMouseLeave).toHaveBeenCalledTimes(1);
    });

    test('calls onClick when container is clicked', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const container = document.querySelector('.context-window-insights-icon');
      fireEvent.click(container!);

      expect(defaultProps.onClick).toHaveBeenCalledTimes(1);
    });
  });

  describe('popup structure', () => {
    test('popup has correct CSS class', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      const popup = document.querySelector('.token-usage-popup');
      expect(popup).toBeInTheDocument();
    });

    test('popup has header section', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      const header = document.querySelector('.token-popup-header');
      expect(header).toBeInTheDocument();

      const title = document.querySelector('.token-popup-title');
      expect(title).toHaveTextContent('Context Window');

      const subtitle = document.querySelector('.token-popup-subtitle');
      expect(subtitle).toBeInTheDocument();
    });

    test('popup has usage section with rows', () => {
      render(<TokenUsagePopup {...defaultProps} show={true} />);

      const usageSection = document.querySelector('.token-usage-section');
      expect(usageSection).toBeInTheDocument();

      const rows = document.querySelectorAll('.token-usage-row');
      expect(rows.length).toBe(3); // Total, Input, Output
    });
  });

  describe('different token limits', () => {
    test('handles small token limits', () => {
      const smallLimit: TokenUsage = {
        total: 2000,
        input: 1200,
        output: 800,
        limit: 4000,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={smallLimit} show={true} />
      );

      expect(screen.getByText('2,000 / 4,000 tokens • 50%')).toBeInTheDocument();
    });

    test('handles large token limits', () => {
      const largeLimit: TokenUsage = {
        total: 500000,
        input: 300000,
        output: 200000,
        limit: 1000000,
      };

      render(
        <TokenUsagePopup {...defaultProps} tokenUsage={largeLimit} show={true} />
      );

      expect(screen.getByText('500,000 / 1,000,000 tokens • 50%')).toBeInTheDocument();
    });
  });

  describe('container element', () => {
    test('container has correct CSS class', () => {
      render(<TokenUsagePopup {...defaultProps} />);

      const container = document.querySelector('.context-window-insights-icon');
      expect(container).toBeInTheDocument();
    });
  });
});
