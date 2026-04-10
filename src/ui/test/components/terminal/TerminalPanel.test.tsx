import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'

import { TerminalPanel } from '../../../components/terminal/TerminalPanel'
import type {
  TerminalApprovalRequest,
  TerminalRunningNotice,
  TerminalSessionRequest,
} from '../../../types'

type TerminalMockInstance = {
  open: ReturnType<typeof vi.fn>
  write: ReturnType<typeof vi.fn>
  writeln: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
  loadAddon: ReturnType<typeof vi.fn>
  scrollToBottom: ReturnType<typeof vi.fn>
  cols: number
  rows: number
}

const terminalInstances: TerminalMockInstance[] = []
const fitAddonInstances: Array<{ fit: ReturnType<typeof vi.fn> }> = []

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn().mockImplementation(function TerminalMock() {
    const instance: TerminalMockInstance = {
      open: vi.fn(),
      write: vi.fn(),
      writeln: vi.fn(),
      dispose: vi.fn(),
      loadAddon: vi.fn(),
      scrollToBottom: vi.fn(),
      cols: 80,
      rows: 24,
    }
    terminalInstances.push(instance)
    return instance
  }),
}))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn().mockImplementation(function FitAddonMock() {
    const instance = { fit: vi.fn() }
    fitAddonInstances.push(instance)
    return instance
  }),
}))

declare global {
  interface Window {
    __terminalWriteOutputDevOnly?: (text: string) => void
    __terminalWriteOutputRawDevOnly?: (text: string) => void
    __terminalWriteCommandDevOnly?: (command: string) => void
  }
}

function createProps(overrides: Partial<ComponentProps<typeof TerminalPanel>> = {}) {
  return {
    approvalRequest: null,
    sessionRequest: null,
    sessionActive: false,
    runningNotice: null,
    commandRunning: false,
    askLevel: 'always',
    onApprovalResponse: vi.fn(),
    onSessionResponse: vi.fn(),
    onStopSession: vi.fn(),
    onKillCommand: vi.fn(),
    onAskLevelChange: vi.fn(),
    onTerminalResize: vi.fn(),
    ...overrides,
  }
}

describe('TerminalPanel', () => {
  const originalRequestAnimationFrame = globalThis.requestAnimationFrame

  beforeEach(() => {
    terminalInstances.length = 0
    fitAddonInstances.length = 0
    vi.clearAllMocks()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    globalThis.requestAnimationFrame = originalRequestAnimationFrame
  })

  test('does not render when there is no interaction and no output', () => {
    const { container } = render(<TerminalPanel {...createProps()} />)

    expect(container.firstChild).toBeNull()
  })

  test('renders when there is a running notice and formats elapsed text', () => {
    const runningNotice: TerminalRunningNotice = {
      request_id: 'run-1',
      command: 'npm run test',
      elapsed_ms: 4200,
    }

    render(<TerminalPanel {...createProps({ runningNotice })} />)

    expect(screen.getByText('Terminal')).toBeInTheDocument()
    expect(screen.getByText(/Still running: npm run test\s+\(4s\)/)).toBeInTheDocument()
  })

  test('calls onSessionResponse for deny and allow actions', () => {
    const onSessionResponse = vi.fn()
    const sessionRequest: TerminalSessionRequest = {
      request_id: 'session-1',
      reason: 'Need multiple commands',
    }

    render(
      <TerminalPanel
        {...createProps({
          sessionRequest,
          onSessionResponse,
        })}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Deny' }))
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))

    expect(onSessionResponse).toHaveBeenNthCalledWith(1, false)
    expect(onSessionResponse).toHaveBeenNthCalledWith(2, true)
  })

  test('approval card actions map to onApprovalResponse payloads', () => {
    const onApprovalResponse = vi.fn()
    const approvalRequest: TerminalApprovalRequest = {
      request_id: 'approval-1',
      command: 'rm -rf dist',
      cwd: '/repo',
    }

    render(
      <TerminalPanel
        {...createProps({
          approvalRequest,
          onApprovalResponse,
        })}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: 'Deny' }))
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Allow & Remember' }))

    expect(onApprovalResponse).toHaveBeenNthCalledWith(1, 'approval-1', false, false)
    expect(onApprovalResponse).toHaveBeenNthCalledWith(2, 'approval-1', true, false)
    expect(onApprovalResponse).toHaveBeenNthCalledWith(3, 'approval-1', true, true)
  })

  test('shows kill button while command is running and click does not toggle panel', () => {
    const onKillCommand = vi.fn()
    const { container } = render(
      <TerminalPanel
        {...createProps({
          commandRunning: true,
          onKillCommand,
        })}
      />
    )

    const toggle = container.querySelector('.terminal-toggle')
    expect(toggle?.textContent).toBe('\u25B2')

    fireEvent.click(screen.getByRole('button', { name: 'Kill' }))

    expect(onKillCommand).toHaveBeenCalledTimes(1)
    expect(toggle?.textContent).toBe('\u25B2')
  })

  test('ask level select change calls onAskLevelChange', () => {
    const onAskLevelChange = vi.fn()
    render(
      <TerminalPanel
        {...createProps({
          commandRunning: true,
          askLevel: 'always',
          onAskLevelChange,
        })}
      />
    )

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'off' } })

    expect(onAskLevelChange).toHaveBeenCalledWith('off')
  })

  test('renders session banner and forwards stop callback while active', () => {
    const onStopSession = vi.fn()
    render(<TerminalPanel {...createProps({ sessionActive: true, onStopSession })} />)

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))

    expect(screen.getByText(/Autonomous mode active/i)).toBeInTheDocument()
    expect(onStopSession).toHaveBeenCalledTimes(1)
  })

  const describeIfDev = import.meta.env.DEV ? describe : describe.skip

  describeIfDev('Dev bridge output behavior', () => {
    test('registers and cleans up dev bridge functions', () => {
      const { unmount } = render(<TerminalPanel {...createProps({ commandRunning: true })} />)

      expect(window.__terminalWriteOutputDevOnly).toBeTypeOf('function')
      expect(window.__terminalWriteOutputRawDevOnly).toBeTypeOf('function')
      expect(window.__terminalWriteCommandDevOnly).toBeTypeOf('function')

      unmount()

      expect(window.__terminalWriteOutputDevOnly).toBeUndefined()
      expect(window.__terminalWriteOutputRawDevOnly).toBeUndefined()
      expect(window.__terminalWriteCommandDevOnly).toBeUndefined()
    })

    test('bridged output initializes xterm and writes line/raw/command output', async () => {
      const onTerminalResize = vi.fn()
      const { container } = render(
        <TerminalPanel
          {...createProps({
            commandRunning: true,
            onTerminalResize,
          })}
        />
      )

      act(() => {
        window.__terminalWriteOutputDevOnly?.('line output')
        window.__terminalWriteOutputRawDevOnly?.('\u001b[31mraw\u001b[0m')
        window.__terminalWriteCommandDevOnly?.('ls -la')
      })

      await waitFor(() => {
        expect(terminalInstances).toHaveLength(1)
      })

      const terminal = terminalInstances[0]
      expect(container.querySelector('.terminal-body')).toBeInTheDocument()
      expect(container.querySelector('.terminal-xterm')).toBeInTheDocument()

      expect(terminal.writeln).toHaveBeenCalledWith('line output')
      expect(terminal.write).toHaveBeenCalledWith('\u001b[31mraw\u001b[0m')
      expect(terminal.writeln).toHaveBeenCalledWith('\u001b[36m$ ls -la\u001b[0m')
      expect(terminal.open).toHaveBeenCalledTimes(1)
      expect(terminal.loadAddon).toHaveBeenCalledTimes(1)
      expect(fitAddonInstances[0].fit).toHaveBeenCalled()
      expect(onTerminalResize).toHaveBeenCalledWith(80, 24)
    })
  })
})
