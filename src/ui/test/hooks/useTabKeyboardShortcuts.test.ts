import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import React from 'react'
import { TabProvider } from '../../contexts/TabContext'
import { useTabKeyboardShortcuts } from '../../hooks/useTabKeyboardShortcuts'
import { useTabs } from '../../contexts/TabContext'

// Wrapper component for testing
const wrapper = ({ children }: { children: React.ReactNode }) =>
  React.createElement(TabProvider, null, children)

// Helper to simulate keyboard events wrapped in act()
function fireKeyDown(
  key: string,
  options: { ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; altKey?: boolean } = {}
): KeyboardEvent {
  const event = new KeyboardEvent('keydown', {
    key,
    ctrlKey: options.ctrlKey ?? false,
    metaKey: options.metaKey ?? false,
    shiftKey: options.shiftKey ?? false,
    altKey: options.altKey ?? false,
    bubbles: true,
    cancelable: true,
  })
  window.dispatchEvent(event)
  return event
}

// Hook that combines both hooks for testing
function useTestHook() {
  const tabContext = useTabs()
  useTabKeyboardShortcuts()
  return tabContext
}

describe('useTabKeyboardShortcuts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    // Clean up any event listeners
    vi.restoreAllMocks()
  })

  describe('Ctrl+T - New Tab', () => {
    test('should create a new tab on Ctrl+T', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })

      expect(result.current.tabs).toHaveLength(2)
    })

    test('should create a new tab on Cmd+T (macOS)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      act(() => {
        fireKeyDown('t', { metaKey: true })
      })

      expect(result.current.tabs).toHaveLength(2)
    })

    test('should create a new tab on Ctrl+T (uppercase T)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      act(() => {
        fireKeyDown('T', { ctrlKey: true })
      })

      expect(result.current.tabs).toHaveLength(2)
    })

    test('should not create tab on Ctrl+Shift+T', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      act(() => {
        fireKeyDown('t', { ctrlKey: true, shiftKey: true })
      })

      expect(result.current.tabs).toHaveLength(1)
    })

    test('should not create tab on Ctrl+Alt+T', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      act(() => {
        fireKeyDown('t', { ctrlKey: true, altKey: true })
      })

      expect(result.current.tabs).toHaveLength(1)
    })

    test('should not create tab on just T key', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      act(() => {
        fireKeyDown('t')
      })

      expect(result.current.tabs).toHaveLength(1)
    })
  })

  describe('Ctrl+W - Close Tab', () => {
    test('should close active tab on Ctrl+W when multiple tabs exist', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create a second tab
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // Now close it
      act(() => {
        fireKeyDown('w', { ctrlKey: true })
      })

      expect(result.current.tabs).toHaveLength(1)
    })

    test('should close active tab on Cmd+W (macOS)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      act(() => {
        fireKeyDown('t', { metaKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      act(() => {
        fireKeyDown('w', { metaKey: true })
      })

      expect(result.current.tabs).toHaveLength(1)
    })

    test('should NOT close tab and SHOULD prevent default when only one tab exists', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)

      let event: KeyboardEvent | null = null
      act(() => {
        event = fireKeyDown('w', { ctrlKey: true })
      })

      expect(result.current.tabs).toHaveLength(1)
      expect(event!.defaultPrevented).toBe(true)
    })

    test('should not close tab on Ctrl+Shift+W', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      act(() => {
        fireKeyDown('w', { ctrlKey: true, shiftKey: true })
      })

      expect(result.current.tabs).toHaveLength(2)
    })

    test('should not close tab on just W key', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      act(() => {
        fireKeyDown('w')
      })

      expect(result.current.tabs).toHaveLength(2)
    })
  })

  describe('Ctrl+Tab - Next Tab', () => {
    test('should switch to next tab on Ctrl+Tab', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create second and third tab
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
        fireKeyDown('t', { ctrlKey: true })
      })

      expect(result.current.tabs).toHaveLength(3)

      // Active tab should be the last created one (tab at index 2)
      const initialActiveId = result.current.activeTabId
      expect(initialActiveId).toBe(result.current.tabs[2].id)

      // Switch to next (should cycle to first)
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)
    })

    test('should cycle from last tab to first tab', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create one more tab
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // We're on the last tab (index 1). Switch to next should go to first (index 0)
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)

      // Switch again should go to second tab (index 1)
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[1].id)
    })

    test('should work with single tab (no-op effectively)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)
      const initialActiveId = result.current.activeTabId

      act(() => {
        fireKeyDown('Tab', { ctrlKey: true })
      })

      // Should stay on same tab (cycle to itself)
      expect(result.current.activeTabId).toBe(initialActiveId)
    })

    test('should work with Cmd+Tab (macOS)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      act(() => {
        fireKeyDown('t', { metaKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // On tab at index 1, switch should go to index 0
      act(() => {
        fireKeyDown('Tab', { metaKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)
    })
  })

  describe('Ctrl+Shift+Tab - Previous Tab', () => {
    test('should switch to previous tab on Ctrl+Shift+Tab', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create second tab
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // We're on second tab (index 1). Switch to previous should go to first (index 0)
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)
    })

    test('should cycle from first tab to last tab', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create two more tabs
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(3)
      // Active tab is now the last created one (index 2)
      expect(result.current.activeTabId).toBe(result.current.tabs[2].id)

      // Switch back to first tab by going previous twice (2 -> 1 -> 0)
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[1].id)

      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)

      // Now switch previous from first tab - should cycle to last (index 2)
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[2].id)
    })

    test('should work with Cmd+Shift+Tab (macOS)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      act(() => {
        fireKeyDown('t', { metaKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // On second tab. Previous should go to first
      act(() => {
        fireKeyDown('Tab', { metaKey: true, shiftKey: true })
      })

      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)
    })

    test('should work with single tab (no-op effectively)', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)
      const initialActiveId = result.current.activeTabId

      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })

      // Should stay on same tab
      expect(result.current.activeTabId).toBe(initialActiveId)
    })
  })

  describe('Event prevention', () => {
    test('should call preventDefault for Ctrl+T', () => {
      renderHook(() => useTestHook(), { wrapper })

      let event: KeyboardEvent | null = null
      act(() => {
        event = fireKeyDown('t', { ctrlKey: true })
      })

      expect(event!.defaultPrevented).toBe(true)
    })

    test('should ALWAYS call preventDefault for Ctrl+W regardless of tab count', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Single tab
      expect(result.current.tabs).toHaveLength(1)
      let event1: KeyboardEvent | null = null
      act(() => {
        event1 = fireKeyDown('w', { ctrlKey: true })
      })
      expect(event1!.defaultPrevented).toBe(true)

      // Multiple tabs
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      let event2: KeyboardEvent | null = null
      act(() => {
        event2 = fireKeyDown('w', { ctrlKey: true })
      })

      expect(event2!.defaultPrevented).toBe(true)
    })

    test('should call preventDefault for Ctrl+Tab', () => {
      renderHook(() => useTestHook(), { wrapper })

      let event: KeyboardEvent | null = null
      act(() => {
        event = fireKeyDown('Tab', { ctrlKey: true })
      })

      expect(event!.defaultPrevented).toBe(true)
    })

    test('should call preventDefault for Ctrl+Shift+Tab', () => {
      renderHook(() => useTestHook(), { wrapper })

      let event: KeyboardEvent | null = null
      act(() => {
        event = fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })

      expect(event!.defaultPrevented).toBe(true)
    })
  })

  describe('Event listener cleanup', () => {
    test('should remove event listener on unmount', () => {
      const addEventListenerSpy = vi.spyOn(window, 'addEventListener')
      const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

      const { unmount } = renderHook(() => useTestHook(), { wrapper })

      expect(addEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function))

      unmount()

      expect(removeEventListenerSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
    })
  })

  describe('Complex scenarios', () => {
    test('should handle rapid tab creation and switching', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create 5 tabs rapidly
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
        fireKeyDown('t', { ctrlKey: true })
        fireKeyDown('t', { ctrlKey: true })
        fireKeyDown('t', { ctrlKey: true })
        fireKeyDown('t', { ctrlKey: true })
      })

      expect(result.current.tabs).toHaveLength(6)

      // Switch through all tabs
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true }) // 5 -> 0
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)

      act(() => {
        fireKeyDown('Tab', { ctrlKey: true }) // 0 -> 1
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[1].id)

      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true }) // 1 -> 0
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)

      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true }) // 0 -> 5 (last)
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[5].id)
    })

    test('should handle create, switch, close cycle', () => {
      const { result } = renderHook(() => useTestHook(), { wrapper })

      // Create tab
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // Switch back to first
      act(() => {
        fireKeyDown('Tab', { ctrlKey: true, shiftKey: true })
      })
      expect(result.current.activeTabId).toBe(result.current.tabs[0].id)

      // Create another tab (now 3 tabs, active on new one at index 2)
      act(() => {
        fireKeyDown('t', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(3)

      // Close current tab
      act(() => {
        fireKeyDown('w', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(2)

      // Close another
      act(() => {
        fireKeyDown('w', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(1)

      // Try to close last one (should not work)
      act(() => {
        fireKeyDown('w', { ctrlKey: true })
      })
      expect(result.current.tabs).toHaveLength(1)
    })
  })
})
