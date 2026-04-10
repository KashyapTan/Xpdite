/**
 * Tests for SessionBanner component.
 *
 * Tests the session mode banner that appears when Xpdite is running
 * autonomously, including the Stop button functionality.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SessionBanner } from '../../../components/terminal/SessionBanner'

describe('SessionBanner', () => {
  const defaultProps = {
    onStop: vi.fn(),
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Content Rendering', () => {
    test('renders autonomous mode active text', () => {
      render(<SessionBanner {...defaultProps} />)

      expect(screen.getByText('Autonomous mode active')).toBeInTheDocument()
    })

    test('renders bolt icon', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const icon = container.querySelector('.session-banner-icon')
      expect(icon).toBeInTheDocument()
    })

    test('renders Stop button', () => {
      render(<SessionBanner {...defaultProps} />)

      const stopButton = screen.getByRole('button', { name: 'Stop' })
      expect(stopButton).toBeInTheDocument()
    })
  })

  describe('Stop Button', () => {
    test('calls onStop when Stop button is clicked', () => {
      const onStop = vi.fn()
      render(<SessionBanner onStop={onStop} />)

      const stopButton = screen.getByRole('button', { name: 'Stop' })
      fireEvent.click(stopButton)

      expect(onStop).toHaveBeenCalledTimes(1)
    })

    test('Stop button has correct class', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const stopButton = container.querySelector('.btn-stop-session')
      expect(stopButton).toBeInTheDocument()
      expect(stopButton?.textContent).toBe('Stop')
    })

    test('multiple clicks call onStop multiple times', () => {
      const onStop = vi.fn()
      render(<SessionBanner onStop={onStop} />)

      const stopButton = screen.getByRole('button', { name: 'Stop' })

      fireEvent.click(stopButton)
      fireEvent.click(stopButton)
      fireEvent.click(stopButton)

      expect(onStop).toHaveBeenCalledTimes(3)
    })
  })

  describe('Component Structure', () => {
    test('renders with correct root class', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const banner = container.querySelector('.terminal-session-banner')
      expect(banner).toBeInTheDocument()
    })

    test('has session-banner-text span', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const textSpan = container.querySelector('.session-banner-text')
      expect(textSpan).toBeInTheDocument()
    })

    test('text content is wrapped in span element', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const textSpan = container.querySelector('.session-banner-text span')
      expect(textSpan).toBeInTheDocument()
      expect(textSpan?.textContent).toBe('Autonomous mode active')
    })
  })

  describe('Icon Rendering', () => {
    test('BoltIcon is rendered with correct size', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const icon = container.querySelector('.session-banner-icon')
      expect(icon).toBeInTheDocument()
      // BoltIcon renders as SVG
      expect(icon?.tagName.toLowerCase()).toBe('svg')
    })

    test('icon is inside the text span', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const textSpan = container.querySelector('.session-banner-text')
      const icon = textSpan?.querySelector('.session-banner-icon')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    test('Stop button is focusable', () => {
      render(<SessionBanner {...defaultProps} />)

      const stopButton = screen.getByRole('button', { name: 'Stop' })
      expect(stopButton).not.toHaveAttribute('tabindex', '-1')
    })

    test('Stop button can be activated with click', () => {
      const onStop = vi.fn()
      render(<SessionBanner onStop={onStop} />)

      const stopButton = screen.getByRole('button', { name: 'Stop' })
      fireEvent.click(stopButton)

      expect(onStop).toHaveBeenCalled()
    })

    test('banner is visible (not hidden)', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const banner = container.querySelector('.terminal-session-banner')
      expect(banner).toBeVisible()
    })
  })

  describe('Layout', () => {
    test('banner contains text and button as siblings', () => {
      const { container } = render(<SessionBanner {...defaultProps} />)

      const banner = container.querySelector('.terminal-session-banner')
      const children = banner?.children

      expect(children?.length).toBe(2)
      expect(children?.[0].classList.contains('session-banner-text')).toBe(true)
      expect(children?.[1].classList.contains('btn-stop-session')).toBe(true)
    })
  })

  describe('Edge Cases', () => {
    test('invokes callback even when callback logic is unusual', () => {
      const onStop = vi.fn()
      render(<SessionBanner onStop={onStop} />)

      const stopButton = screen.getByRole('button', { name: 'Stop' })

      fireEvent.click(stopButton)
      expect(onStop).toHaveBeenCalled()
    })

    test('renders correctly with different callback functions', () => {
      const onStop1 = vi.fn()
      const { rerender } = render(<SessionBanner onStop={onStop1} />)

      fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
      expect(onStop1).toHaveBeenCalledTimes(1)

      const onStop2 = vi.fn()
      rerender(<SessionBanner onStop={onStop2} />)

      fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
      expect(onStop2).toHaveBeenCalledTimes(1)
      expect(onStop1).toHaveBeenCalledTimes(1)
    })
  })
})
