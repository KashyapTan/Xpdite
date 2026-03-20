import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import React from 'react'
import { WebSocketProvider, useWebSocket } from '../../contexts/WebSocketContext'
import { discoverServerPort } from '../../services/portDiscovery'

// Mock the portDiscovery module
vi.mock('../../services/portDiscovery', () => ({
  discoverServerPort: vi.fn().mockResolvedValue(8000),
  getWsBaseUrl: vi.fn().mockReturnValue('ws://localhost:8000'),
  resetDiscovery: vi.fn(),
}))

// Mock WebSocket class
interface MockWebSocketInstance {
  url: string
  readyState: number
  onopen: ((this: WebSocket, ev: Event) => void) | null
  onclose: ((this: WebSocket, ev: CloseEvent) => void) | null
  onmessage: ((this: WebSocket, ev: MessageEvent) => void) | null
  onerror: ((this: WebSocket, ev: Event) => void) | null
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

let mockWsInstances: MockWebSocketInstance[] = []
let MockWebSocketClass: ReturnType<typeof vi.fn>

function createMockWebSocket() {
  MockWebSocketClass = vi.fn(function (this: unknown, url: string) {
    const instance: MockWebSocketInstance = {
      url,
      readyState: WebSocket.CONNECTING,
      onopen: null,
      onclose: null,
      onmessage: null,
      onerror: null,
      send: vi.fn(),
      close: vi.fn().mockImplementation(function (this: MockWebSocketInstance) {
        this.readyState = WebSocket.CLOSED
      }),
    }
    mockWsInstances.push(instance)
    return instance
  })

  // Add static constants
  MockWebSocketClass.CONNECTING = 0
  MockWebSocketClass.OPEN = 1
  MockWebSocketClass.CLOSING = 2
  MockWebSocketClass.CLOSED = 3

  return MockWebSocketClass
}

// Wrapper component for testing
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <WebSocketProvider>{children}</WebSocketProvider>
)

describe('WebSocketContext', () => {
  const originalWebSocket = global.WebSocket

  beforeEach(() => {
    vi.useFakeTimers()
    mockWsInstances = []
    global.WebSocket = createMockWebSocket() as unknown as typeof WebSocket
    vi.clearAllMocks()
    vi.mocked(discoverServerPort).mockResolvedValue(8000)
  })

  afterEach(() => {
    vi.useRealTimers()
    global.WebSocket = originalWebSocket
  })

  describe('useWebSocket hook', () => {
    test('should throw error when used outside WebSocketProvider', () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      expect(() => {
        renderHook(() => useWebSocket())
      }).toThrow('useWebSocket must be used within WebSocketProvider')

      consoleSpy.mockRestore()
    })
  })

  describe('Initial State', () => {
    test('should start with isConnected as false', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      expect(result.current.isConnected).toBe(false)
    })

    test('should create WebSocket connection on mount', async () => {
      renderHook(() => useWebSocket(), { wrapper })

      // Let the async connect function run
      await act(async () => {
        await vi.runAllTimersAsync()
      })

      expect(mockWsInstances.length).toBeGreaterThanOrEqual(1)
      expect(mockWsInstances[0].url).toBe('ws://localhost:8000/ws')
    })
  })

  describe('Connection Lifecycle', () => {
    test('should set isConnected to true when WebSocket opens', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Simulate WebSocket opening
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(result.current.isConnected).toBe(true)
    })

    test('should set isConnected to false when WebSocket closes', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Open the connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(result.current.isConnected).toBe(true)

      // Close the connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      expect(result.current.isConnected).toBe(false)
    })

    test('should attempt to reconnect after connection closes', async () => {
      renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const initialInstanceCount = mockWsInstances.length

      // Close the connection (triggers reconnect)
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      // Advance timers to trigger reconnect
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000) // Initial reconnect delay
        await vi.runAllTimersAsync()
      })

      expect(mockWsInstances.length).toBeGreaterThan(initialInstanceCount)
    })

    test('should use exponential backoff for reconnection', async () => {
      renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // First close (2s delay)
      act(() => {
        const ws = mockWsInstances[mockWsInstances.length - 1]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      const countAfterFirstClose = mockWsInstances.length

      // Advance 1.9s - should not reconnect yet
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1900)
      })

      expect(mockWsInstances.length).toBe(countAfterFirstClose)

      // Advance another 200ms (total 2.1s) - should reconnect
      await act(async () => {
        await vi.advanceTimersByTimeAsync(200)
        await vi.runAllTimersAsync()
      })

      expect(mockWsInstances.length).toBeGreaterThan(countAfterFirstClose)

      // Second close (4s delay)
      act(() => {
        const ws = mockWsInstances[mockWsInstances.length - 1]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      const countAfterSecondClose = mockWsInstances.length

      // Advance 3s - should not reconnect yet
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000)
      })

      expect(mockWsInstances.length).toBe(countAfterSecondClose)

      // Advance another 1.5s - should reconnect
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1500)
        await vi.runAllTimersAsync()
      })

      expect(mockWsInstances.length).toBeGreaterThan(countAfterSecondClose)
    })

    test('should reset backoff delay on successful connection', async () => {
      renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Simulate multiple disconnects to increase backoff
      for (let i = 0; i < 3; i++) {
        act(() => {
          const ws = mockWsInstances[mockWsInstances.length - 1]
          ws.readyState = WebSocket.CLOSED
          ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
        })

        await act(async () => {
          await vi.advanceTimersByTimeAsync(30000) // Max delay
          await vi.runAllTimersAsync()
        })
      }

      // Now successfully connect
      act(() => {
        const ws = mockWsInstances[mockWsInstances.length - 1]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      // Disconnect again
      act(() => {
        const ws = mockWsInstances[mockWsInstances.length - 1]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      const countAfterClose = mockWsInstances.length

      // Should reconnect after 2s (reset delay), not 30s
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100)
        await vi.runAllTimersAsync()
      })

      expect(mockWsInstances.length).toBeGreaterThan(countAfterClose)
    })

    test('should close WebSocket on unmount', async () => {
      const { unmount } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const ws = mockWsInstances[0]

      unmount()

      expect(ws.close).toHaveBeenCalled()
    })

    test('should cancel reconnection on unmount', async () => {
      const { unmount } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Trigger disconnect to start reconnect timer
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      const countBeforeUnmount = mockWsInstances.length

      unmount()

      // Advance past reconnect delay
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000)
      })

      // No new connections should be made after unmount
      expect(mockWsInstances.length).toBe(countBeforeUnmount)
    })
  })

  describe('send()', () => {
    test('should send JSON stringified message when connected', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      const testMessage = { type: 'test', data: { foo: 'bar' } }

      act(() => {
        result.current.send(testMessage)
      })

      expect(mockWsInstances[0].send).toHaveBeenCalledWith(JSON.stringify(testMessage))
    })

    test('should not send when WebSocket is not open', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Don't open the connection
      const testMessage = { type: 'test' }

      act(() => {
        result.current.send(testMessage)
      })

      expect(mockWsInstances[0].send).not.toHaveBeenCalled()
    })

    test('should not send when WebSocket is closed', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Open then close
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      const testMessage = { type: 'test' }

      act(() => {
        result.current.send(testMessage)
      })

      expect(mockWsInstances[0].send).not.toHaveBeenCalled()
    })
  })

  describe('subscribe()', () => {
    test('should register a message handler', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler = vi.fn()

      act(() => {
        result.current.subscribe(handler)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      // Handler should receive __ws_connected message
      expect(handler).toHaveBeenCalledWith({ type: '__ws_connected' })
    })

    test('should return unsubscribe function', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler = vi.fn()
      let unsubscribe: (() => void) | undefined

      act(() => {
        unsubscribe = result.current.subscribe(handler)
      })

      // Unsubscribe
      act(() => {
        unsubscribe?.()
      })

      // Open connection - handler should NOT be called
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(handler).not.toHaveBeenCalled()
    })

    test('should handle multiple subscribers', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler1 = vi.fn()
      const handler2 = vi.fn()
      const handler3 = vi.fn()

      act(() => {
        result.current.subscribe(handler1)
        result.current.subscribe(handler2)
        result.current.subscribe(handler3)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(handler1).toHaveBeenCalled()
      expect(handler2).toHaveBeenCalled()
      expect(handler3).toHaveBeenCalled()
    })

    test('should deliver messages to all subscribers', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler1 = vi.fn()
      const handler2 = vi.fn()

      act(() => {
        result.current.subscribe(handler1)
        result.current.subscribe(handler2)
      })

      // Open connection and clear mock calls from __ws_connected
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      handler1.mockClear()
      handler2.mockClear()

      // Receive a message
      const testMessage = { type: 'chat', content: 'hello' }
      act(() => {
        const ws = mockWsInstances[0]
        ws.onmessage?.call(ws as unknown as WebSocket, {
          data: JSON.stringify(testMessage)
        } as MessageEvent)
      })

      expect(handler1).toHaveBeenCalledWith(testMessage)
      expect(handler2).toHaveBeenCalledWith(testMessage)
    })
  })

  describe('Pseudo-messages', () => {
    test('should emit __ws_connected when WebSocket opens', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler = vi.fn()

      act(() => {
        result.current.subscribe(handler)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(handler).toHaveBeenCalledWith({ type: '__ws_connected' })
    })

    test('should emit __ws_disconnected when WebSocket closes', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler = vi.fn()

      act(() => {
        result.current.subscribe(handler)
      })

      // Open then close connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      handler.mockClear()

      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      expect(handler).toHaveBeenCalledWith({ type: '__ws_disconnected' })
    })

    test('should emit pseudo-messages to all subscribers', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler1 = vi.fn()
      const handler2 = vi.fn()

      act(() => {
        result.current.subscribe(handler1)
        result.current.subscribe(handler2)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(handler1).toHaveBeenCalledWith({ type: '__ws_connected' })
      expect(handler2).toHaveBeenCalledWith({ type: '__ws_connected' })

      handler1.mockClear()
      handler2.mockClear()

      // Close connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      expect(handler1).toHaveBeenCalledWith({ type: '__ws_disconnected' })
      expect(handler2).toHaveBeenCalledWith({ type: '__ws_disconnected' })
    })
  })

  describe('Message Handling', () => {
    test('should parse and deliver JSON messages', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler = vi.fn()

      act(() => {
        result.current.subscribe(handler)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      handler.mockClear()

      // Receive a JSON message
      const testMessage = { type: 'response', content: 'test', nested: { value: 123 } }
      act(() => {
        const ws = mockWsInstances[0]
        ws.onmessage?.call(ws as unknown as WebSocket, {
          data: JSON.stringify(testMessage)
        } as MessageEvent)
      })

      expect(handler).toHaveBeenCalledWith(testMessage)
    })

    test('should log error for invalid JSON messages', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const handler = vi.fn()

      act(() => {
        result.current.subscribe(handler)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      handler.mockClear()

      // Receive invalid JSON
      act(() => {
        const ws = mockWsInstances[0]
        ws.onmessage?.call(ws as unknown as WebSocket, {
          data: 'not valid json {'
        } as MessageEvent)
      })

      expect(consoleSpy).toHaveBeenCalledWith('Failed to parse WebSocket message:', expect.any(Error))
      expect(handler).not.toHaveBeenCalled()

      consoleSpy.mockRestore()
    })

    test('should handle subscribe/unsubscribe during message delivery', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      let unsubscribe2: (() => void) | undefined
      const handler1 = vi.fn()
      const handler2 = vi.fn().mockImplementation(() => {
        // Unsubscribe during iteration
        unsubscribe2?.()
      })
      const handler3 = vi.fn()

      act(() => {
        result.current.subscribe(handler1)
        unsubscribe2 = result.current.subscribe(handler2)
        result.current.subscribe(handler3)
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      // All handlers should have been called due to snapshot during iteration
      expect(handler1).toHaveBeenCalled()
      expect(handler2).toHaveBeenCalled()
      expect(handler3).toHaveBeenCalled()
    })
  })

  describe('Error Handling', () => {
    test('should log WebSocket errors', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Trigger error
      act(() => {
        const ws = mockWsInstances[0]
        ws.onerror?.call(ws as unknown as WebSocket, new Event('error'))
      })

      expect(consoleSpy).toHaveBeenCalledWith('WebSocket error:', expect.any(Event))

      consoleSpy.mockRestore()
    })

    test('should continue functioning after error followed by close', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(result.current.isConnected).toBe(true)

      // Trigger error then close
      act(() => {
        const ws = mockWsInstances[0]
        ws.onerror?.call(ws as unknown as WebSocket, new Event('error'))
      })

      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      expect(result.current.isConnected).toBe(false)

      // Should attempt reconnect
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100)
        await vi.runAllTimersAsync()
      })

      // Reconnect should open
      act(() => {
        const ws = mockWsInstances[mockWsInstances.length - 1]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(result.current.isConnected).toBe(true)

      consoleSpy.mockRestore()
    })

    test('should reconnect after a discovery failure during connect()', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      vi.mocked(discoverServerPort)
        .mockRejectedValueOnce(new Error('Backend unavailable'))
        .mockResolvedValue(8000)

      renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      expect(consoleSpy).toHaveBeenCalledWith('WebSocket connect failed:', expect.any(Error))
      expect(mockWsInstances.length).toBeGreaterThanOrEqual(1)

      consoleSpy.mockRestore()
    })

    test('should isolate subscriber errors and continue notifying other subscribers', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      const failingHandler = vi.fn(() => {
        throw new Error('handler failed')
      })
      const healthyHandler = vi.fn()

      act(() => {
        result.current.subscribe(failingHandler)
        result.current.subscribe(healthyHandler)
      })

      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(consoleSpy).toHaveBeenCalledWith('WebSocket subscriber error:', expect.any(Error))
      expect(healthyHandler).toHaveBeenCalledWith({ type: '__ws_connected' })

      healthyHandler.mockClear()
      failingHandler.mockClear()

      const testMessage = { type: 'chat', content: 'still works' }
      act(() => {
        const ws = mockWsInstances[0]
        ws.onmessage?.call(ws as unknown as WebSocket, {
          data: JSON.stringify(testMessage),
        } as MessageEvent)
      })

      expect(failingHandler).toHaveBeenCalledWith(testMessage)
      expect(healthyHandler).toHaveBeenCalledWith(testMessage)

      consoleSpy.mockRestore()
    })
  })

  describe('isConnected state', () => {
    test('should reflect WebSocket connection state', async () => {
      const { result } = renderHook(() => useWebSocket(), { wrapper })

      await act(async () => {
        await vi.runAllTimersAsync()
      })

      // Initially not connected
      expect(result.current.isConnected).toBe(false)

      // Open connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.OPEN
        ws.onopen?.call(ws as unknown as WebSocket, new Event('open'))
      })

      expect(result.current.isConnected).toBe(true)

      // Close connection
      act(() => {
        const ws = mockWsInstances[0]
        ws.readyState = WebSocket.CLOSED
        ws.onclose?.call(ws as unknown as WebSocket, new CloseEvent('close'))
      })

      expect(result.current.isConnected).toBe(false)
    })
  })
})
