/**
 * Tests for ScreenshotChips component.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ScreenshotChips } from '../../../components/input/ScreenshotChips';
import type { Screenshot } from '../../../types';

describe('ScreenshotChips', () => {
  const mockOnRemove = vi.fn();

  const mockScreenshots: Screenshot[] = [
    {
      id: 'ss-1',
      name: 'Screenshot 1',
      thumbnail: 'base64ImageData1',
    },
    {
      id: 'ss-2',
      name: 'Screenshot 2',
      thumbnail: 'base64ImageData2',
    },
    {
      id: 'ss-3',
      name: 'Screenshot 3',
      thumbnail: '', // No thumbnail
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('empty state', () => {
    test('returns null when screenshots array is empty', () => {
      const { container } = render(
        <ScreenshotChips screenshots={[]} onRemove={mockOnRemove} />
      );

      expect(container.firstChild).toBeNull();
    });
  });

  describe('rendering screenshots', () => {
    test('renders all screenshot chips', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      expect(screen.getByText('SS1')).toBeInTheDocument();
      expect(screen.getByText('SS2')).toBeInTheDocument();
      expect(screen.getByText('SS3')).toBeInTheDocument();
    });

    test('renders container with correct class', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const container = screen.getByText('SS1').closest('.context-chips');
      expect(container).toBeInTheDocument();
    });

    test('renders thumbnail images for screenshots with thumbnails', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const images = screen.getAllByRole('img');
      // 2 thumbnails + 2 hover previews = 4 images (only for screenshots with thumbnails)
      // SS3 has no thumbnail, so it shows CameraIcon instead
      expect(images.length).toBeGreaterThanOrEqual(2);

      const thumbnailImage = screen.getAllByAltText('Screenshot 1')[0];
      expect(thumbnailImage).toHaveAttribute(
        'src',
        'data:image/png;base64,base64ImageData1'
      );
    });

    test('renders CameraIcon fallback when thumbnail is missing', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      // The third screenshot has no thumbnail, so it should show a camera icon
      const chipPreviews = document.querySelectorAll('.chip-preview');
      expect(chipPreviews.length).toBe(3);

      // The third chip preview should contain an SVG (CameraIcon) instead of an image
      const thirdChipPreview = chipPreviews[2];
      const svg = thirdChipPreview.querySelector('svg');
      expect(svg).toBeInTheDocument();
    });

    test('renders chip names with correct numbering', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const chipNames = document.querySelectorAll('.chip-name');
      expect(chipNames[0]).toHaveTextContent('SS1');
      expect(chipNames[1]).toHaveTextContent('SS2');
      expect(chipNames[2]).toHaveTextContent('SS3');
    });
  });

  describe('remove button', () => {
    test('renders remove button for each chip', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const removeButtons = document.querySelectorAll('.chip-remove');
      expect(removeButtons.length).toBe(3);
    });

    test('remove button has correct aria-label', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      expect(screen.getByLabelText('Remove Screenshot 1')).toBeInTheDocument();
      expect(screen.getByLabelText('Remove Screenshot 2')).toBeInTheDocument();
      expect(screen.getByLabelText('Remove Screenshot 3')).toBeInTheDocument();
    });

    test('remove button has correct title attribute', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const removeButtons = document.querySelectorAll('.chip-remove');
      removeButtons.forEach((button) => {
        expect(button).toHaveAttribute('title', 'Remove screenshot');
      });
    });

    test('calls onRemove with correct id when remove button is clicked', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      fireEvent.click(screen.getByLabelText('Remove Screenshot 1'));
      expect(mockOnRemove).toHaveBeenCalledWith('ss-1');

      fireEvent.click(screen.getByLabelText('Remove Screenshot 2'));
      expect(mockOnRemove).toHaveBeenCalledWith('ss-2');

      fireEvent.click(screen.getByLabelText('Remove Screenshot 3'));
      expect(mockOnRemove).toHaveBeenCalledWith('ss-3');
    });

    test('remove button has type="button"', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const removeButtons = document.querySelectorAll('.chip-remove');
      removeButtons.forEach((button) => {
        expect(button).toHaveAttribute('type', 'button');
      });
    });
  });

  describe('hover preview', () => {
    test('renders hover preview container for each chip', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const hoverPreviews = document.querySelectorAll('.chip-hover-preview');
      expect(hoverPreviews.length).toBe(3);
    });

    test('hover preview shows full screenshot name', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const hoverPreviewNames = document.querySelectorAll('.hover-preview-name');
      expect(hoverPreviewNames[0]).toHaveTextContent('Screenshot 1');
      expect(hoverPreviewNames[1]).toHaveTextContent('Screenshot 2');
      expect(hoverPreviewNames[2]).toHaveTextContent('Screenshot 3');
    });

    test('hover preview contains larger thumbnail image', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const hoverPreviewImages = document.querySelectorAll('.hover-preview-img');
      // Only screenshots with thumbnails have preview images
      expect(hoverPreviewImages.length).toBe(2);
    });
  });

  describe('single screenshot', () => {
    test('renders correctly with a single screenshot', () => {
      const singleScreenshot: Screenshot[] = [
        {
          id: 'single-ss',
          name: 'Single Screenshot',
          thumbnail: 'singleImageData',
        },
      ];

      render(
        <ScreenshotChips screenshots={singleScreenshot} onRemove={mockOnRemove} />
      );

      expect(screen.getByText('SS1')).toBeInTheDocument();
      expect(screen.getByLabelText('Remove Single Screenshot')).toBeInTheDocument();
    });
  });

  describe('chip structure', () => {
    test('each chip has correct CSS class structure', () => {
      render(
        <ScreenshotChips screenshots={mockScreenshots} onRemove={mockOnRemove} />
      );

      const chips = document.querySelectorAll('.context-chip');
      expect(chips.length).toBe(3);

      chips.forEach((chip) => {
        expect(chip.querySelector('.chip-preview')).toBeInTheDocument();
        expect(chip.querySelector('.chip-name')).toBeInTheDocument();
        expect(chip.querySelector('.chip-remove')).toBeInTheDocument();
        expect(chip.querySelector('.chip-hover-preview')).toBeInTheDocument();
      });
    });
  });

  describe('screenshot without name', () => {
    test('uses fallback name in aria-label when screenshot name is missing', () => {
      const screenshotWithoutName: Screenshot[] = [
        {
          id: 'no-name-ss',
          name: '',
          thumbnail: 'data',
        },
      ];

      render(
        <ScreenshotChips screenshots={screenshotWithoutName} onRemove={mockOnRemove} />
      );

      // When name is empty, aria-label falls back to "screenshot 1"
      expect(screen.getByLabelText('Remove screenshot 1')).toBeInTheDocument();
    });
  });
});
