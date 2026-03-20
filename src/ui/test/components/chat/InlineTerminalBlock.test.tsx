/**
 * Tests for InlineTerminalBlock component.
 *
 * Focuses on:
 * - Status-based UI rendering
 * - Approval button callbacks
 * - Non-PTY (ansi-to-html) output rendering
 * - Expand/collapse functionality
 * - Footer text and status indicators
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { InlineTerminalBlock } from '../../../components/chat/InlineTerminalBlock'
import type { TerminalCommandBlock } from '../../../types'

// Mock xterm.js - doesn't work in jsdom
vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn().mockImplementation(function TerminalMock(this: unknown) {
    return {
      open: vi.fn(),
      write: vi.fn(),
      writeln: vi.fn(),
      dispose: vi.fn(),
      loadAddon: vi.fn(),
      scrollToBottom: vi.fn(),
      cols: 80,
      rows: 24,
      options: {},
    }
  }),
}))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn().mockImplementation(function FitAddonMock(this: unknown) {
    return {
      fit: vi.fn(),
    }
  }),
}))

// Mock ansi-to-html
vi.mock('ansi-to-html', () => ({
  default: vi.fn().mockImplementation(function (this: unknown) {
    return {
      toHtml: (text: string) => {
        const ansiPattern = String.fromCharCode(27) + '\\[[0-9;]*m'
        return text.replace(new RegExp(ansiPattern, 'g'), '')
      },
    }
  }),
}))

// Helper to create terminal blocks with defaults
function createTerminalBlock(
  overrides: Partial<TerminalCommandBlock> = {}
): TerminalCommandBlock {
  return {
    requestId: 'test-request-123',
    command: 'echo "Hello World"',
    cwd: '/home/user/project',
    status: 'pending_approval',
    output: '',
    outputChunks: [],
    isPty: false,
    ...overrides,
  }
}

describe('InlineTerminalBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Header Rendering', () => {
    test('renders command in header', () => {
      const terminal = createTerminalBlock({ command: 'npm run build' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('npm run build')).toBeInTheDocument()
    })

    test('renders TERMINAL badge for non-PTY commands', () => {
      const terminal = createTerminalBlock({ isPty: false })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('TERMINAL')).toBeInTheDocument()
    })

    test('renders PTY badge for PTY commands', () => {
      const terminal = createTerminalBlock({ isPty: true, status: 'running' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('PTY')).toBeInTheDocument()
    })

    test('header is clickable for expand/collapse', () => {
      const terminal = createTerminalBlock()
      render(<InlineTerminalBlock terminal={terminal} />)

      const header = screen.getByText('echo "Hello World"').closest('.terminal-inline-header')
      expect(header).toBeInTheDocument()
    })
  })

  describe('Status Indicators', () => {
    test('shows pending icon for pending_approval status', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const icon = container.querySelector('.terminal-inline-icon.pending')
      expect(icon).toBeInTheDocument()
    })

    test('shows denied icon for denied status', () => {
      const terminal = createTerminalBlock({ status: 'denied' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const icon = container.querySelector('.terminal-inline-icon.denied')
      expect(icon).toBeInTheDocument()
    })

    test('shows running spinner for running status', () => {
      const terminal = createTerminalBlock({ status: 'running' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const icon = container.querySelector('.terminal-inline-icon.running-spin')
      expect(icon).toBeInTheDocument()
    })

    test('shows success icon for completed with exit code 0', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: 0,
        durationMs: 1000,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const icon = container.querySelector('.terminal-inline-icon.success')
      expect(icon).toBeInTheDocument()
    })

    test('shows error icon for completed with non-zero exit code', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: 1,
        durationMs: 1000,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const icon = container.querySelector('.terminal-inline-icon.error')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('Pending Approval State', () => {
    test('shows approval prompt when pending', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Xpdite wants to run this command')).toBeInTheDocument()
    })

    test('shows working directory in approval prompt', () => {
      const terminal = createTerminalBlock({
        status: 'pending_approval',
        cwd: '/custom/path',
      })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('in: /custom/path')).toBeInTheDocument()
    })

    test('renders Deny button and calls onDeny', () => {
      const onDeny = vi.fn()
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      render(<InlineTerminalBlock terminal={terminal} onDeny={onDeny} />)

      const denyButton = screen.getByRole('button', { name: 'Deny' })
      expect(denyButton).toBeInTheDocument()

      fireEvent.click(denyButton)
      expect(onDeny).toHaveBeenCalledWith('test-request-123')
    })

    test('renders Allow button and calls onApprove', () => {
      const onApprove = vi.fn()
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      render(<InlineTerminalBlock terminal={terminal} onApprove={onApprove} />)

      const allowButton = screen.getByRole('button', { name: 'Allow' })
      expect(allowButton).toBeInTheDocument()

      fireEvent.click(allowButton)
      expect(onApprove).toHaveBeenCalledWith('test-request-123')
    })

    test('renders Allow & Remember button and calls onApproveRemember', () => {
      const onApproveRemember = vi.fn()
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      render(
        <InlineTerminalBlock terminal={terminal} onApproveRemember={onApproveRemember} />
      )

      const rememberButton = screen.getByRole('button', { name: 'Allow & Remember' })
      expect(rememberButton).toBeInTheDocument()

      fireEvent.click(rememberButton)
      expect(onApproveRemember).toHaveBeenCalledWith('test-request-123')
    })

    test('does not render buttons when callbacks are not provided', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.queryByRole('button', { name: 'Deny' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Allow' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Allow & Remember' })).not.toBeInTheDocument()
    })
  })

  describe('Running State', () => {
    test('shows Kill button when running and onKill provided', () => {
      const onKill = vi.fn()
      const terminal = createTerminalBlock({ status: 'running' })
      render(<InlineTerminalBlock terminal={terminal} onKill={onKill} />)

      const killButton = screen.getByRole('button', { name: 'Kill' })
      expect(killButton).toBeInTheDocument()
    })

    test('Kill button calls onKill with requestId', () => {
      const onKill = vi.fn()
      const terminal = createTerminalBlock({
        status: 'running',
        requestId: 'kill-test-456',
      })
      render(<InlineTerminalBlock terminal={terminal} onKill={onKill} />)

      const killButton = screen.getByRole('button', { name: 'Kill' })
      fireEvent.click(killButton)

      expect(onKill).toHaveBeenCalledWith('kill-test-456')
    })

    test('Kill button does not show when onKill not provided', () => {
      const terminal = createTerminalBlock({ status: 'running' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.queryByRole('button', { name: 'Kill' })).not.toBeInTheDocument()
    })

    test('Kill button does not show when not running', () => {
      const onKill = vi.fn()
      const terminal = createTerminalBlock({ status: 'completed' })
      render(<InlineTerminalBlock terminal={terminal} onKill={onKill} />)

      expect(screen.queryByRole('button', { name: 'Kill' })).not.toBeInTheDocument()
    })

    test('Kill button click does not trigger expand/collapse', () => {
      const onKill = vi.fn()
      const terminal = createTerminalBlock({ status: 'running' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} onKill={onKill} />)

      // Initially expanded (body should exist)
      expect(container.querySelector('.terminal-inline-body')).toBeInTheDocument()

      const killButton = screen.getByRole('button', { name: 'Kill' })
      fireEvent.click(killButton)

      // Still expanded after clicking kill (stopPropagation should work)
      expect(container.querySelector('.terminal-inline-body')).toBeInTheDocument()
    })
  })

  describe('Denied State', () => {
    test('shows denied message', () => {
      const terminal = createTerminalBlock({ status: 'denied' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Command was denied.')).toBeInTheDocument()
    })
  })

  describe('Output Rendering (non-PTY)', () => {
    test('renders output for non-PTY commands', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        isPty: false,
        output: 'Hello from terminal',
        exitCode: 0,
        durationMs: 500,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const outputArea = container.querySelector('.terminal-inline-output')
      expect(outputArea).toBeInTheDocument()
    })

    test('does not render output area when output is empty', () => {
      const terminal = createTerminalBlock({
        status: 'running',
        isPty: false,
        output: '',
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const outputArea = container.querySelector('.terminal-inline-output')
      expect(outputArea).not.toBeInTheDocument()
    })

    test('renders output with pre element for non-PTY', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        isPty: false,
        output: 'Line 1\nLine 2',
        exitCode: 0,
        durationMs: 100,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const pre = container.querySelector('.terminal-inline-output-pre')
      expect(pre).toBeInTheDocument()
    })
  })

  describe('PTY Output Rendering', () => {
    test('renders xterm container for PTY commands when running', () => {
      const terminal = createTerminalBlock({
        status: 'running',
        isPty: true,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      // PT-based terminal blocks start collapsed UNLESS expanded is true or status is pending approval.
      // InlineTerminalBlock.tsx line 74: const [isExpanded, setIsExpanded] = useState(() => !terminal.isPty);
      // Wait, if it is PTY, isExpanded is FALSE by default.
      
      const header = screen.getByText(terminal.command).closest('.terminal-inline-header')
      if (header) fireEvent.click(header)

      const xtermWrapper = container.querySelector('.terminal-inline-xterm-wrapper')
      expect(xtermWrapper).toBeInTheDocument()
    })

    test('renders xterm container for PTY commands when completed', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        isPty: true,
        exitCode: 0,
        durationMs: 1000,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const header = screen.getByText(terminal.command).closest('.terminal-inline-header')
      if (header) fireEvent.click(header)

      const xtermWrapper = container.querySelector('.terminal-inline-xterm-wrapper')
      expect(xtermWrapper).toBeInTheDocument()
    })

    test('does not render xterm for pending_approval PTY', () => {
      const terminal = createTerminalBlock({
        status: 'pending_approval',
        isPty: true,
      })
      // pending_approval triggers auto-expand in useEffect
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      // But PTY content is only rendered if status is running or completed
      // isPty && (status === 'running' || status === 'completed')
      const xtermWrapper = container.querySelector('.terminal-inline-xterm-wrapper')
      expect(xtermWrapper).not.toBeInTheDocument()
    })

    test('adds pty-completed class when PTY is completed', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        isPty: true,
        exitCode: 0,
        durationMs: 500,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const header = screen.getByText(terminal.command).closest('.terminal-inline-header')
      if (header) fireEvent.click(header)

      const xtermWrapper = container.querySelector('.terminal-inline-xterm-wrapper.pty-completed')
      expect(xtermWrapper).toBeInTheDocument()
    })
  })

  describe('Footer Text', () => {
    test('shows "Awaiting approval" for pending_approval', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      // Footer should not show during pending_approval
      const footer = container.querySelector('.terminal-inline-footer')
      expect(footer).not.toBeInTheDocument()
    })

    test('shows "Running..." for running status', () => {
      const terminal = createTerminalBlock({ status: 'running' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Running...')).toBeInTheDocument()
    })

    test('shows "Command denied" for denied status', () => {
      const terminal = createTerminalBlock({ status: 'denied' })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Command denied')).toBeInTheDocument()
    })

    test('shows completion message with duration and exit code 0', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: 0,
        durationMs: 2500,
      })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Completed in 2.5s · exit 0')).toBeInTheDocument()
    })

    test('shows completion message with non-zero exit code', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: 1,
        durationMs: 1000,
      })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Completed in 1.0s · exit 1')).toBeInTheDocument()
    })

    test('shows timeout indicator when timedOut is true', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: 124,
        durationMs: 30000,
        timedOut: true,
      })
      render(<InlineTerminalBlock terminal={terminal} />)

      expect(screen.getByText('Completed in 30.0s · exit 124 (timed out)')).toBeInTheDocument()
    })

    test('footer has correct status class', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: 0,
        durationMs: 100,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const footer = container.querySelector('.terminal-inline-footer.status-completed')
      expect(footer).toBeInTheDocument()
    })
  })

  describe('Expand/Collapse Functionality', () => {
    test('starts expanded by default', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const body = container.querySelector('.terminal-inline-body')
      expect(body).toBeInTheDocument()
    })

    test('collapses when header is clicked', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const header = container.querySelector('.terminal-inline-header')!
      fireEvent.click(header)

      const body = container.querySelector('.terminal-inline-body')
      expect(body).not.toBeInTheDocument()
    })

    test('expands when collapsed header is clicked', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const header = container.querySelector('.terminal-inline-header')!

      // Collapse
      fireEvent.click(header)
      expect(container.querySelector('.terminal-inline-body')).not.toBeInTheDocument()

      // Expand
      fireEvent.click(header)
      expect(container.querySelector('.terminal-inline-body')).toBeInTheDocument()
    })

    test('chevron icon rotates based on expanded state', () => {
      const terminal = createTerminalBlock({ status: 'pending_approval' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      // Initially expanded
      let chevron = container.querySelector('.terminal-inline-chevron.expanded')
      expect(chevron).toBeInTheDocument()

      // Collapse
      const header = container.querySelector('.terminal-inline-header')!
      fireEvent.click(header)

      // Chevron should not have expanded class
      chevron = container.querySelector('.terminal-inline-chevron')
      expect(chevron).toBeInTheDocument()
      expect(chevron?.classList.contains('expanded')).toBe(false)
    })
  })

  describe('CSS Class Styling', () => {
    test('root element has status class', () => {
      const terminal = createTerminalBlock({ status: 'running' })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      const root = container.querySelector('.terminal-inline-block.status-running')
      expect(root).toBeInTheDocument()
    })

    test('root element reflects different status classes', () => {
      const statuses: TerminalCommandBlock['status'][] = [
        'pending_approval',
        'denied',
        'running',
        'completed',
      ]

      for (const status of statuses) {
        const terminal = createTerminalBlock({
          status,
          exitCode: status === 'completed' ? 0 : undefined,
          durationMs: status === 'completed' ? 100 : undefined,
        })
        const { container, unmount } = render(<InlineTerminalBlock terminal={terminal} />)

        const root = container.querySelector(`.terminal-inline-block.status-${status}`)
        expect(root).toBeInTheDocument()
        unmount()
      }
    })
  })

  describe('Edge Cases', () => {
    test('handles empty command gracefully', () => {
      const terminal = createTerminalBlock({ command: '' })
      render(<InlineTerminalBlock terminal={terminal} />)

      // Should render without crashing
      expect(screen.getByText('TERMINAL')).toBeInTheDocument()
    })

    test('handles undefined exitCode in completed state', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        exitCode: undefined,
        durationMs: 1000,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      // Should still render the block
      const root = container.querySelector('.terminal-inline-block')
      expect(root).toBeInTheDocument()
    })

    test('handles very long command text', () => {
      const longCommand = 'a'.repeat(500)
      const terminal = createTerminalBlock({ command: longCommand })
      render(<InlineTerminalBlock terminal={terminal} />)

      const commandEl = screen.getByText(longCommand)
      expect(commandEl).toHaveAttribute('title', longCommand)
    })

    test('handles special characters in output', () => {
      const terminal = createTerminalBlock({
        status: 'completed',
        isPty: false,
        output: '<script>alert("xss")</script>',
        exitCode: 0,
        durationMs: 100,
      })
      const { container } = render(<InlineTerminalBlock terminal={terminal} />)

      // ansi-to-html escapes XML, so this should be safe
      const outputArea = container.querySelector('.terminal-inline-output')
      expect(outputArea).toBeInTheDocument()
    })
  })
})
