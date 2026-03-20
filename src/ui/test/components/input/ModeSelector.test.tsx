/**
 * Tests for ModeSelector component.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ModeSelector } from '../../../components/input/ModeSelector';
import type { CaptureMode } from '../../../types';

describe('ModeSelector', () => {
  const defaultProps = {
    captureMode: 'fullscreen' as CaptureMode,
    meetingRecordingMode: false,
    onFullscreenMode: vi.fn(),
    onPrecisionMode: vi.fn(),
    onMeetingMode: vi.fn(),
    regionSSIcon: '/icons/region.svg',
    fullscreenSSIcon: '/icons/fullscreen.svg',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    test('renders all three mode buttons', () => {
      render(<ModeSelector {...defaultProps} />);

      expect(screen.getByLabelText('Precision capture mode')).toBeInTheDocument();
      expect(screen.getByLabelText('Fullscreen capture mode')).toBeInTheDocument();
      expect(screen.getByLabelText('Meeting recorder mode')).toBeInTheDocument();
    });

    test('renders tablist role for accessibility', () => {
      render(<ModeSelector {...defaultProps} />);

      expect(screen.getByRole('tablist', { name: 'Capture mode selector' })).toBeInTheDocument();
    });

    test('renders icon images for precision and fullscreen modes', () => {
      render(<ModeSelector {...defaultProps} />);

      const regionIcon = screen.getByAltText('Region Screenshot Mode');
      const fullscreenIcon = screen.getByAltText('Full Screen Screenshot Mode');

      expect(regionIcon).toHaveAttribute('src', '/icons/region.svg');
      expect(fullscreenIcon).toHaveAttribute('src', '/icons/fullscreen.svg');
    });

    test('renders SVG icon for meeting mode', () => {
      render(<ModeSelector {...defaultProps} />);

      const meetingButton = screen.getByLabelText('Meeting recorder mode');
      const svgIcon = meetingButton.querySelector('svg');

      expect(svgIcon).toBeInTheDocument();
      expect(svgIcon).toHaveClass('meeting-recording-icon');
    });
  });

  describe('visual indicator for selected mode', () => {
    test('fullscreen mode shows active class when selected', () => {
      render(<ModeSelector {...defaultProps} captureMode="fullscreen" />);

      const fullscreenButton = screen.getByLabelText('Fullscreen capture mode');
      const precisionButton = screen.getByLabelText('Precision capture mode');
      const meetingButton = screen.getByLabelText('Meeting recorder mode');

      expect(fullscreenButton).toHaveClass('mode-selector-button-active');
      expect(precisionButton).not.toHaveClass('mode-selector-button-active');
      expect(meetingButton).not.toHaveClass('mode-selector-button-active');
    });

    test('precision mode shows active class when selected', () => {
      render(<ModeSelector {...defaultProps} captureMode="precision" />);

      const fullscreenButton = screen.getByLabelText('Fullscreen capture mode');
      const precisionButton = screen.getByLabelText('Precision capture mode');
      const meetingButton = screen.getByLabelText('Meeting recorder mode');

      expect(precisionButton).toHaveClass('mode-selector-button-active');
      expect(fullscreenButton).not.toHaveClass('mode-selector-button-active');
      expect(meetingButton).not.toHaveClass('mode-selector-button-active');
    });

    test('meeting mode shows active class when meetingRecordingMode is true', () => {
      render(<ModeSelector {...defaultProps} meetingRecordingMode={true} />);

      const fullscreenButton = screen.getByLabelText('Fullscreen capture mode');
      const precisionButton = screen.getByLabelText('Precision capture mode');
      const meetingButton = screen.getByLabelText('Meeting recorder mode');

      expect(meetingButton).toHaveClass('mode-selector-button-active');
      expect(fullscreenButton).not.toHaveClass('mode-selector-button-active');
      expect(precisionButton).not.toHaveClass('mode-selector-button-active');
    });

    test('meeting mode takes precedence over captureMode', () => {
      render(
        <ModeSelector
          {...defaultProps}
          captureMode="precision"
          meetingRecordingMode={true}
        />
      );

      const meetingButton = screen.getByLabelText('Meeting recorder mode');
      const precisionButton = screen.getByLabelText('Precision capture mode');

      expect(meetingButton).toHaveClass('mode-selector-button-active');
      expect(precisionButton).not.toHaveClass('mode-selector-button-active');
    });
  });

  describe('aria-pressed attributes', () => {
    test('sets aria-pressed="true" on selected mode', () => {
      render(<ModeSelector {...defaultProps} captureMode="fullscreen" />);

      expect(screen.getByLabelText('Fullscreen capture mode')).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByLabelText('Precision capture mode')).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByLabelText('Meeting recorder mode')).toHaveAttribute('aria-pressed', 'false');
    });

    test('sets aria-pressed="true" on meeting mode when active', () => {
      render(<ModeSelector {...defaultProps} meetingRecordingMode={true} />);

      expect(screen.getByLabelText('Meeting recorder mode')).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByLabelText('Fullscreen capture mode')).toHaveAttribute('aria-pressed', 'false');
      expect(screen.getByLabelText('Precision capture mode')).toHaveAttribute('aria-pressed', 'false');
    });
  });

  describe('click interactions', () => {
    test('calls onPrecisionMode when precision button is clicked', () => {
      render(<ModeSelector {...defaultProps} />);

      fireEvent.click(screen.getByLabelText('Precision capture mode'));

      expect(defaultProps.onPrecisionMode).toHaveBeenCalledTimes(1);
    });

    test('calls onFullscreenMode when fullscreen button is clicked', () => {
      render(<ModeSelector {...defaultProps} />);

      fireEvent.click(screen.getByLabelText('Fullscreen capture mode'));

      expect(defaultProps.onFullscreenMode).toHaveBeenCalledTimes(1);
    });

    test('calls onMeetingMode when meeting button is clicked', () => {
      render(<ModeSelector {...defaultProps} />);

      fireEvent.click(screen.getByLabelText('Meeting recorder mode'));

      expect(defaultProps.onMeetingMode).toHaveBeenCalledTimes(1);
    });
  });

  describe('button titles (tooltips)', () => {
    test('precision button has correct title', () => {
      render(<ModeSelector {...defaultProps} />);

      expect(screen.getByLabelText('Precision capture mode')).toHaveAttribute(
        'title',
        'Talk to a specific region of your screen'
      );
    });

    test('fullscreen button has correct title', () => {
      render(<ModeSelector {...defaultProps} />);

      expect(screen.getByLabelText('Fullscreen capture mode')).toHaveAttribute(
        'title',
        'Talk to anything on your screen'
      );
    });

    test('meeting button has correct title', () => {
      render(<ModeSelector {...defaultProps} />);

      expect(screen.getByLabelText('Meeting recorder mode')).toHaveAttribute(
        'title',
        'Meeting recorder mode'
      );
    });
  });

  describe('button types', () => {
    test('all buttons have type="button" to prevent form submission', () => {
      render(<ModeSelector {...defaultProps} />);

      const buttons = screen.getAllByRole('button');
      buttons.forEach((button) => {
        expect(button).toHaveAttribute('type', 'button');
      });
    });
  });
});
