/**
 * Tests for TerminalCard component.
 *
 * Tests the terminal history card that shows collapsed terminal events
 * from past conversations with expand/collapse functionality.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TerminalCard } from '../../../components/terminal/TerminalCard'
import type { TerminalEvent } from '../../../types'

// Helper to create terminal events with defaults
function createTerminalEvent(overrides: Partial<TerminalEvent> = {}): TerminalEvent {
  return {
    id: 'event-1',
    message_index: 0,
    command: 'echo "test"',
    exit_code: 0,
    output_preview: 'test output',
    cwd: '/home/user',
    duration_ms: 100,
    timed_out: false,
    denied: false,
    pty: false,
    background: false,
    created_at: Date.now(),
    ...overrides,
  }
}

describe('TerminalCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Basic Rendering', () => {
    test('renders terminal history card with events', () => {
      const events = [createTerminalEvent()]
      render(<TerminalCard events={events} />)

      expect(screen.getByText(/Terminal Activity/)).toBeInTheDocument()
    })

    test('returns null when events array is empty', () => {
      const { container } = render(<TerminalCard events={[]} />)
      expect(container.firstChild).toBeNull()
    })

    test('returns null when events is undefined', () => {
      const { container } = render(<TerminalCard events={undefined as unknown as TerminalEvent[]} />)
      expect(container.firstChild).toBeNull()
    })
  })

  describe('Header Information', () => {
    test('shows correct command count for single command', () => {
      const events = [createTerminalEvent()]
      render(<TerminalCard events={events} />)

      expect(screen.getByText(/1 command/)).toBeInTheDocument()
      expect(screen.queryByText(/commands/)).not.toBeInTheDocument()
    })

    test('shows correct command count for multiple commands', () => {
      const events = [
        createTerminalEvent({ id: '1' }),
        createTerminalEvent({ id: '2' }),
        createTerminalEvent({ id: '3' }),
      ]
      render(<TerminalCard events={events} />)

      expect(screen.getByText(/3 commands/)).toBeInTheDocument()
    })

    test('shows total duration', () => {
      const events = [
        createTerminalEvent({ id: '1', duration_ms: 1500 }),
        createTerminalEvent({ id: '2', duration_ms: 2500 }),
      ]
      render(<TerminalCard events={events} />)

      // Total: 4000ms = 4.0s
      expect(screen.getByText(/4\.0s total/)).toBeInTheDocument()
    })

    test('shows terminal icon in header', () => {
      const events = [createTerminalEvent()]
      const { container } = render(<TerminalCard events={events} />)

      const icon = container.querySelector('.terminal-history-icon')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('Expand/Collapse Functionality', () => {
    test('starts collapsed by default', () => {
      const events = [createTerminalEvent()]
      const { container } = render(<TerminalCard events={events} />)

      const body = container.querySelector('.terminal-history-body')
      expect(body).not.toBeInTheDocument()
    })

    test('expands when header is clicked', () => {
      const events = [createTerminalEvent()]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const body = container.querySelector('.terminal-history-body')
      expect(body).toBeInTheDocument()
    })

    test('collapses when expanded header is clicked', () => {
      const events = [createTerminalEvent()]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!

      // Expand
      fireEvent.click(header)
      expect(container.querySelector('.terminal-history-body')).toBeInTheDocument()

      // Collapse
      fireEvent.click(header)
      expect(container.querySelector('.terminal-history-body')).not.toBeInTheDocument()
    })

    test('shows chevron right when collapsed', () => {
      const events = [createTerminalEvent()]
      const { container } = render(<TerminalCard events={events} />)

      // ChevronRightIcon should be present when collapsed
      const toggle = container.querySelector('.terminal-history-toggle')
      expect(toggle).toBeInTheDocument()
    })

    test('shows chevron down when expanded', () => {
      const events = [createTerminalEvent()]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      // ChevronDownIcon should be present when expanded
      const toggle = container.querySelector('.terminal-history-toggle')
      expect(toggle).toBeInTheDocument()
    })
  })

  describe('Event Rows', () => {
    test('renders all events when expanded', () => {
      const events = [
        createTerminalEvent({ id: '1', command: 'npm install' }),
        createTerminalEvent({ id: '2', command: 'npm test' }),
        createTerminalEvent({ id: '3', command: 'npm build' }),
      ]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.getByText('npm install')).toBeInTheDocument()
      expect(screen.getByText('npm test')).toBeInTheDocument()
      expect(screen.getByText('npm build')).toBeInTheDocument()
    })

    test('shows command text in each row', () => {
      const events = [createTerminalEvent({ command: 'git status' })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.getByText('git status')).toBeInTheDocument()
    })

    test('shows duration for each event', () => {
      const events = [createTerminalEvent({ duration_ms: 2500 })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.getByText('2.5s')).toBeInTheDocument()
    })
  })

  describe('Event Status Icons', () => {
    test('shows success icon for exit code 0', () => {
      const events = [createTerminalEvent({ exit_code: 0 })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const icon = container.querySelector('.terminal-event-icon.success')
      expect(icon).toBeInTheDocument()
    })

    test('shows error icon for non-zero exit code', () => {
      const events = [createTerminalEvent({ exit_code: 1 })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const icon = container.querySelector('.terminal-event-icon.error')
      expect(icon).toBeInTheDocument()
    })

    test('shows denied icon for denied commands', () => {
      const events = [createTerminalEvent({ denied: true })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const icon = container.querySelector('.terminal-event-icon.denied')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('Event Tags', () => {
    test('shows PTY tag for PTY commands', () => {
      const events = [createTerminalEvent({ pty: true })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.getByText('(PTY)')).toBeInTheDocument()
    })

    test('shows timeout tag for timed out commands', () => {
      const events = [createTerminalEvent({ timed_out: true })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.getByText('(timeout)')).toBeInTheDocument()
    })

    test('shows exit code tag for non-zero non-denied commands', () => {
      const events = [createTerminalEvent({ exit_code: 127, denied: false })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.getByText('exit 127')).toBeInTheDocument()
    })

    test('does not show exit code tag for denied commands', () => {
      const events = [createTerminalEvent({ exit_code: 1, denied: true })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.queryByText('exit 1')).not.toBeInTheDocument()
    })

    test('does not show exit code tag for successful commands', () => {
      const events = [createTerminalEvent({ exit_code: 0 })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      expect(screen.queryByText('exit 0')).not.toBeInTheDocument()
    })
  })

  describe('Output Preview', () => {
    test('output is hidden by default in event row', () => {
      const events = [createTerminalEvent({ output_preview: 'hidden output' })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const output = container.querySelector('.terminal-event-output')
      expect(output).not.toBeInTheDocument()
    })

    test('shows output when event row is clicked', () => {
      const events = [createTerminalEvent({ output_preview: 'visible output' })]
      const { container } = render(<TerminalCard events={events} />)

      // Expand card
      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      // Click event summary to show output
      const eventSummary = container.querySelector('.terminal-event-summary')!
      fireEvent.click(eventSummary)

      expect(screen.getByText('visible output')).toBeInTheDocument()
    })

    test('hides output when event row is clicked again', () => {
      const events = [createTerminalEvent({ output_preview: 'toggle output' })]
      const { container } = render(<TerminalCard events={events} />)

      // Expand card
      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const eventSummary = container.querySelector('.terminal-event-summary')!

      // Show output
      fireEvent.click(eventSummary)
      expect(screen.getByText('toggle output')).toBeInTheDocument()

      // Hide output
      fireEvent.click(eventSummary)
      expect(screen.queryByText('toggle output')).not.toBeInTheDocument()
    })

    test('does not show output section if output_preview is empty', () => {
      const events = [createTerminalEvent({ output_preview: '' })]
      const { container } = render(<TerminalCard events={events} />)

      // Expand card
      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      // Click event summary
      const eventSummary = container.querySelector('.terminal-event-summary')!
      fireEvent.click(eventSummary)

      const output = container.querySelector('.terminal-event-output')
      expect(output).not.toBeInTheDocument()
    })

    test('renders output in pre element', () => {
      const events = [createTerminalEvent({ output_preview: 'preformatted text' })]
      const { container } = render(<TerminalCard events={events} />)

      // Expand card
      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      // Click event summary
      const eventSummary = container.querySelector('.terminal-event-summary')!
      fireEvent.click(eventSummary)

      const pre = container.querySelector('.terminal-event-output pre')
      expect(pre).toBeInTheDocument()
      expect(pre?.textContent).toBe('preformatted text')
    })
  })

  describe('Multiple Events', () => {
    test('each event can be toggled independently', () => {
      const events = [
        createTerminalEvent({ id: '1', command: 'cmd1', output_preview: 'output1' }),
        createTerminalEvent({ id: '2', command: 'cmd2', output_preview: 'output2' }),
      ]
      const { container } = render(<TerminalCard events={events} />)

      // Expand card
      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      const summaries = container.querySelectorAll('.terminal-event-summary')
      expect(summaries).toHaveLength(2)

      // Show first event's output
      fireEvent.click(summaries[0])
      expect(screen.getByText('output1')).toBeInTheDocument()
      expect(screen.queryByText('output2')).not.toBeInTheDocument()

      // Show second event's output
      fireEvent.click(summaries[1])
      expect(screen.getByText('output1')).toBeInTheDocument()
      expect(screen.getByText('output2')).toBeInTheDocument()

      // Hide first event's output
      fireEvent.click(summaries[0])
      expect(screen.queryByText('output1')).not.toBeInTheDocument()
      expect(screen.getByText('output2')).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    test('handles events with zero duration', () => {
      const events = [createTerminalEvent({ duration_ms: 0 })]
      render(<TerminalCard events={events} />)

      expect(screen.getByText(/0\.0s total/)).toBeInTheDocument()
    })

    test('handles events with very long duration', () => {
      const events = [createTerminalEvent({ duration_ms: 3600000 })] // 1 hour
      render(<TerminalCard events={events} />)

      expect(screen.getByText(/3600\.0s total/)).toBeInTheDocument()
    })

    test('handles events with empty command', () => {
      const events = [createTerminalEvent({ command: '' })]
      const { container } = render(<TerminalCard events={events} />)

      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      // Should render without crashing
      const row = container.querySelector('.terminal-event-row')
      expect(row).toBeInTheDocument()
    })

    test('handles events with special characters in output', () => {
      const events = [
        createTerminalEvent({ output_preview: '<div>HTML</div> & "quotes"' }),
      ]
      const { container } = render(<TerminalCard events={events} />)

      // Expand card
      const header = container.querySelector('.terminal-history-header')!
      fireEvent.click(header)

      // Click event summary
      const eventSummary = container.querySelector('.terminal-event-summary')!
      fireEvent.click(eventSummary)

      expect(screen.getByText('<div>HTML</div> & "quotes"')).toBeInTheDocument()
    })
  })
})
