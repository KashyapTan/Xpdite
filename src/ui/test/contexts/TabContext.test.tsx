import { describe, expect, test, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import React from 'react'
import { TabProvider, useTabs } from '../../contexts/TabContext'
import type { TabSnapshot } from '../../types'

// Wrapper component for testing
const wrapper = ({ children }: { children: React.ReactNode }) => (
  <TabProvider>{children}</TabProvider>
)

describe('TabContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Initial State', () => {
    test('should have a default tab on initialization', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      expect(result.current.tabs).toHaveLength(1)
      expect(result.current.tabs[0]).toEqual({ id: 'default', title: 'Chat' })
      expect(result.current.activeTabId).toBe('default')
    })

    test('should have empty queueMap initially', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      expect(result.current.queueMap).toEqual({})
    })
  })

  describe('useTabs hook', () => {
    test('should throw error when used outside TabProvider', () => {
      // Suppress console.error for this test
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

      expect(() => {
        renderHook(() => useTabs())
      }).toThrow('useTabs must be used within <TabProvider>')

      consoleSpy.mockRestore()
    })
  })

  describe('createTab()', () => {
    test('should create a new tab and return its ID', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      expect(newTabId).not.toBeNull()
      expect(result.current.tabs).toHaveLength(2)
      expect(result.current.tabs[1].title).toBe('New Chat')
      expect(result.current.activeTabId).toBe(newTabId)
    })

    test('should switch to the new tab after creation', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      act(() => {
        result.current.createTab()
      })

      // Active tab should be the newly created one (not 'default')
      expect(result.current.activeTabId).not.toBe('default')
      expect(result.current.tabs.find(t => t.id === result.current.activeTabId)).toBeDefined()
    })

    test('should generate unique tab IDs', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const tabIds: (string | null)[] = []
      act(() => {
        tabIds.push(result.current.createTab())
        tabIds.push(result.current.createTab())
        tabIds.push(result.current.createTab())
      })

      const uniqueIds = new Set(tabIds)
      expect(uniqueIds.size).toBe(tabIds.length)
    })

    test('should call beforeSwitch and afterSwitch callbacks when creating tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const beforeSwitchMock = vi.fn()
      const afterSwitchMock = vi.fn()

      act(() => {
        result.current.registerBeforeSwitch(beforeSwitchMock)
        result.current.registerAfterSwitch(afterSwitchMock)
      })

      act(() => {
        result.current.createTab()
      })

      expect(beforeSwitchMock).toHaveBeenCalledWith('default')
      expect(afterSwitchMock).toHaveBeenCalled()
    })
  })

  describe('Max Tabs Limit', () => {
    test('should enforce max tabs limit of 10', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      // Create 9 tabs (we already have 1 default tab)
      act(() => {
        for (let i = 0; i < 9; i++) {
          result.current.createTab()
        }
      })

      expect(result.current.tabs).toHaveLength(10)

      // Try to create one more tab
      let extraTabId: string | null = null
      act(() => {
        extraTabId = result.current.createTab()
      })

      expect(extraTabId).toBeNull()
      expect(result.current.tabs).toHaveLength(10)
    })

    test('should allow creating tab after closing one at max limit', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      // Create 9 tabs to reach limit
      act(() => {
        for (let i = 0; i < 9; i++) {
          result.current.createTab()
        }
      })

      expect(result.current.tabs).toHaveLength(10)

      // Close one tab
      const tabToClose = result.current.tabs[5].id
      act(() => {
        result.current.closeTab(tabToClose)
      })

      expect(result.current.tabs).toHaveLength(9)

      // Now we should be able to create another tab
      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      expect(newTabId).not.toBeNull()
      expect(result.current.tabs).toHaveLength(10)
    })
  })

  describe('closeTab()', () => {
    test('should close a tab by ID', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      expect(result.current.tabs).toHaveLength(2)

      act(() => {
        result.current.closeTab(newTabId!)
      })

      expect(result.current.tabs).toHaveLength(1)
      expect(result.current.tabs.find(t => t.id === newTabId)).toBeUndefined()
    })

    test('should not close the last remaining tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      act(() => {
        result.current.closeTab('default')
      })

      expect(result.current.tabs).toHaveLength(1)
      expect(result.current.tabs[0].id).toBe('default')
    })

    test('should switch to nearest tab when closing active tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const tabIds: (string | null)[] = []
      act(() => {
        tabIds.push(result.current.createTab())
        tabIds.push(result.current.createTab())
        tabIds.push(result.current.createTab())
      })

      // Active tab should be the last created one
      const activeTabId = result.current.activeTabId
      const activeTabIndex = result.current.tabs.findIndex(t => t.id === activeTabId)

      act(() => {
        result.current.closeTab(activeTabId)
      })

      // Should switch to nearest remaining tab
      expect(result.current.activeTabId).not.toBe(activeTabId)
      expect(result.current.tabs.find(t => t.id === result.current.activeTabId)).toBeDefined()
      // The new active tab should be at the same or previous index
      const newActiveTabIndex = result.current.tabs.findIndex(t => t.id === result.current.activeTabId)
      expect(newActiveTabIndex).toBeLessThanOrEqual(activeTabIndex)
    })

    test('should clean up queueMap when closing tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
        result.current.setQueueItems(newTabId!, [
          { item_id: '1', preview: 'test', position: 0 }
        ])
      })

      expect(result.current.queueMap[newTabId!]).toBeDefined()

      act(() => {
        result.current.closeTab(newTabId!)
      })

      expect(result.current.queueMap[newTabId!]).toBeUndefined()
    })

    test('should call onTabClosed callback when closing tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const onTabClosedMock = vi.fn()

      act(() => {
        result.current.registerOnTabClosed(onTabClosedMock)
      })

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      act(() => {
        result.current.closeTab(newTabId!)
      })

      expect(onTabClosedMock).toHaveBeenCalledWith(newTabId)
    })

    test('should call afterSwitch when closing active tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const afterSwitchMock = vi.fn()

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      // Clear mock from createTab call
      act(() => {
        result.current.registerAfterSwitch(afterSwitchMock)
      })

      act(() => {
        result.current.closeTab(newTabId!)
      })

      // afterSwitch should be called with the new active tab ID
      expect(afterSwitchMock).toHaveBeenCalled()
    })

    test('should not call afterSwitch when closing non-active tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const afterSwitchMock = vi.fn()

      let tab1Id: string | null = null
      let tab2Id: string | null = null
      act(() => {
        tab1Id = result.current.createTab()
        tab2Id = result.current.createTab()
      })

      // Switch to tab2 (the last one created is already active)
      expect(result.current.activeTabId).toBe(tab2Id)

      act(() => {
        result.current.registerAfterSwitch(afterSwitchMock)
      })

      // Close tab1 (not active)
      act(() => {
        result.current.closeTab(tab1Id!)
      })

      // afterSwitch should NOT be called since we closed a non-active tab
      expect(afterSwitchMock).not.toHaveBeenCalled()
    })
  })

  describe('switchTab()', () => {
    test('should switch to a different tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      act(() => {
        result.current.createTab()
      })

      // Now switch back to default
      act(() => {
        result.current.switchTab('default')
      })

      expect(result.current.activeTabId).toBe('default')
    })

    test('should not switch if already on the same tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const beforeSwitchMock = vi.fn()
      const afterSwitchMock = vi.fn()

      act(() => {
        result.current.registerBeforeSwitch(beforeSwitchMock)
        result.current.registerAfterSwitch(afterSwitchMock)
      })

      act(() => {
        result.current.switchTab('default')
      })

      expect(beforeSwitchMock).not.toHaveBeenCalled()
      expect(afterSwitchMock).not.toHaveBeenCalled()
    })

    test('should not switch to non-existent tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const beforeSwitchMock = vi.fn()
      const afterSwitchMock = vi.fn()

      act(() => {
        result.current.registerBeforeSwitch(beforeSwitchMock)
        result.current.registerAfterSwitch(afterSwitchMock)
      })

      act(() => {
        result.current.switchTab('non-existent-tab-id')
      })

      expect(result.current.activeTabId).toBe('default')
      expect(beforeSwitchMock).not.toHaveBeenCalled()
      expect(afterSwitchMock).not.toHaveBeenCalled()
    })

    test('should call beforeSwitch and afterSwitch callbacks', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      const beforeSwitchMock = vi.fn()
      const afterSwitchMock = vi.fn()

      act(() => {
        result.current.registerBeforeSwitch(beforeSwitchMock)
        result.current.registerAfterSwitch(afterSwitchMock)
      })

      act(() => {
        result.current.switchTab('default')
      })

      expect(beforeSwitchMock).toHaveBeenCalledWith(newTabId)
      expect(afterSwitchMock).toHaveBeenCalledWith('default')
    })
  })

  describe('updateTabTitle()', () => {
    test('should update tab title', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      act(() => {
        result.current.updateTabTitle('default', 'My Custom Title')
      })

      expect(result.current.tabs[0].title).toBe('My Custom Title')
    })

    test('should only update the specified tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      let newTabId: string | null = null
      act(() => {
        newTabId = result.current.createTab()
      })

      act(() => {
        result.current.updateTabTitle('default', 'Updated Default')
      })

      const defaultTab = result.current.tabs.find(t => t.id === 'default')
      const newTab = result.current.tabs.find(t => t.id === newTabId)

      expect(defaultTab?.title).toBe('Updated Default')
      expect(newTab?.title).toBe('New Chat')
    })
  })

  describe('setQueueItems()', () => {
    test('should set queue items for a tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const queueItems = [
        { item_id: '1', preview: 'Item 1', position: 0 },
        { item_id: '2', preview: 'Item 2', position: 1 },
      ]

      act(() => {
        result.current.setQueueItems('default', queueItems)
      })

      expect(result.current.queueMap['default']).toEqual(queueItems)
    })

    test('should update queue items for existing tab', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      act(() => {
        result.current.setQueueItems('default', [
          { item_id: '1', preview: 'Item 1', position: 0 }
        ])
      })

      act(() => {
        result.current.setQueueItems('default', [
          { item_id: '2', preview: 'Item 2', position: 0 }
        ])
      })

      expect(result.current.queueMap['default']).toEqual([
        { item_id: '2', preview: 'Item 2', position: 0 }
      ])
    })
  })

  describe('Snapshot Registry', () => {
    test('getTabSnapshot() should return undefined for non-existent snapshot', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const snapshot = result.current.getTabSnapshot('non-existent')

      expect(snapshot).toBeUndefined()
    })

    test('setTabSnapshot() and getTabSnapshot() should persist and retrieve snapshots', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const mockSnapshot: TabSnapshot = {
        chat: {
          chatHistory: [],
          currentQuery: 'test query',
          response: '',
          thinking: '',
          isThinking: false,
          thinkingCollapsed: false,
          toolCalls: [],
          contentBlocks: [],
          conversationId: null,
          query: '',
          canSubmit: true,
          status: 'ready',
          error: '',
        },
        screenshots: {
          screenshots: [],
          captureMode: 'none',
          meetingRecordingMode: false,
        },
        tokens: {
          tokenUsage: { total: 100, input: 50, output: 50, limit: 4096 },
        },
        terminal: {
          terminalSessionActive: false,
          terminalSessionRequest: null,
        },
        generatingModel: 'gpt-4',
      }

      act(() => {
        result.current.setTabSnapshot('default', mockSnapshot)
      })

      const retrieved = result.current.getTabSnapshot('default')
      expect(retrieved).toEqual(mockSnapshot)
    })

    test('deleteTabSnapshot() should remove a snapshot', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const mockSnapshot: TabSnapshot = {
        chat: {
          chatHistory: [],
          currentQuery: '',
          response: '',
          thinking: '',
          isThinking: false,
          thinkingCollapsed: false,
          toolCalls: [],
          contentBlocks: [],
          conversationId: null,
          query: '',
          canSubmit: true,
          status: 'ready',
          error: '',
        },
        screenshots: {
          screenshots: [],
          captureMode: 'none',
          meetingRecordingMode: false,
        },
        tokens: {
          tokenUsage: { total: 0, input: 0, output: 0, limit: 4096 },
        },
        terminal: {
          terminalSessionActive: false,
          terminalSessionRequest: null,
        },
        generatingModel: '',
      }

      act(() => {
        result.current.setTabSnapshot('default', mockSnapshot)
      })

      expect(result.current.getTabSnapshot('default')).toBeDefined()

      act(() => {
        result.current.deleteTabSnapshot('default')
      })

      expect(result.current.getTabSnapshot('default')).toBeUndefined()
    })

    test('snapshots should persist across tab switches', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const mockSnapshot: TabSnapshot = {
        chat: {
          chatHistory: [],
          currentQuery: 'persistent query',
          response: '',
          thinking: '',
          isThinking: false,
          thinkingCollapsed: false,
          toolCalls: [],
          contentBlocks: [],
          conversationId: null,
          query: '',
          canSubmit: true,
          status: 'ready',
          error: '',
        },
        screenshots: {
          screenshots: [],
          captureMode: 'none',
          meetingRecordingMode: false,
        },
        tokens: {
          tokenUsage: { total: 0, input: 0, output: 0, limit: 4096 },
        },
        terminal: {
          terminalSessionActive: false,
          terminalSessionRequest: null,
        },
        generatingModel: '',
      }

      act(() => {
        result.current.setTabSnapshot('default', mockSnapshot)
      })

      act(() => {
        result.current.createTab()
      })

      act(() => {
        result.current.switchTab('default')
      })

      // Snapshot should still be there
      const retrieved = result.current.getTabSnapshot('default')
      expect(retrieved?.chat.currentQuery).toBe('persistent query')
    })
  })

  describe('Callback Registration', () => {
    test('registerBeforeSwitch() should return unsubscribe function', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const mockCallback = vi.fn()
      let unsubscribe: (() => void) | undefined

      act(() => {
        unsubscribe = result.current.registerBeforeSwitch(mockCallback)
      })

      act(() => {
        result.current.createTab()
      })

      expect(mockCallback).toHaveBeenCalled()

      // Unsubscribe
      act(() => {
        unsubscribe?.()
      })

      mockCallback.mockClear()

      act(() => {
        result.current.switchTab('default')
      })

      expect(mockCallback).not.toHaveBeenCalled()
    })

    test('registerAfterSwitch() should return unsubscribe function', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const mockCallback = vi.fn()
      let unsubscribe: (() => void) | undefined

      act(() => {
        unsubscribe = result.current.registerAfterSwitch(mockCallback)
      })

      act(() => {
        result.current.createTab()
      })

      expect(mockCallback).toHaveBeenCalled()

      // Unsubscribe
      act(() => {
        unsubscribe?.()
      })

      mockCallback.mockClear()

      act(() => {
        result.current.switchTab('default')
      })

      expect(mockCallback).not.toHaveBeenCalled()
    })

    test('registerOnTabClosed() should return unsubscribe function', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const mockCallback = vi.fn()
      let unsubscribe: (() => void) | undefined

      act(() => {
        unsubscribe = result.current.registerOnTabClosed(mockCallback)
      })

      let tab1Id: string | null = null
      act(() => {
        tab1Id = result.current.createTab()
      })

      act(() => {
        result.current.closeTab(tab1Id!)
      })

      expect(mockCallback).toHaveBeenCalledWith(tab1Id)

      // Unsubscribe
      act(() => {
        unsubscribe?.()
      })

      mockCallback.mockClear()

      let tab2Id: string | null = null
      act(() => {
        tab2Id = result.current.createTab()
      })

      act(() => {
        result.current.closeTab(tab2Id!)
      })

      expect(mockCallback).not.toHaveBeenCalled()
    })

    test('unsubscribing a different callback should not affect the current one', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const callback1 = vi.fn()
      const callback2 = vi.fn()

      let unsubscribe1: (() => void) | undefined

      act(() => {
        unsubscribe1 = result.current.registerBeforeSwitch(callback1)
      })

      // Register callback2, which replaces callback1
      act(() => {
        result.current.registerBeforeSwitch(callback2)
      })

      // Unsubscribe callback1 should not affect callback2
      act(() => {
        unsubscribe1?.()
      })

      act(() => {
        result.current.createTab()
      })

      expect(callback2).toHaveBeenCalled()
    })

    test('unsubscribing old afterSwitch callback should not clear replacement callback', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const callback1 = vi.fn()
      const callback2 = vi.fn()
      let unsubscribe1: (() => void) | undefined

      act(() => {
        unsubscribe1 = result.current.registerAfterSwitch(callback1)
      })

      act(() => {
        result.current.registerAfterSwitch(callback2)
      })

      act(() => {
        unsubscribe1?.()
      })

      act(() => {
        result.current.createTab()
      })

      expect(callback1).not.toHaveBeenCalled()
      expect(callback2).toHaveBeenCalled()
    })

    test('unsubscribing old onTabClosed callback should not clear replacement callback', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const callback1 = vi.fn()
      const callback2 = vi.fn()
      let unsubscribe1: (() => void) | undefined

      act(() => {
        unsubscribe1 = result.current.registerOnTabClosed(callback1)
      })

      act(() => {
        result.current.registerOnTabClosed(callback2)
      })

      let tabId: string | null = null
      act(() => {
        tabId = result.current.createTab()
      })

      act(() => {
        unsubscribe1?.()
      })

      act(() => {
        result.current.closeTab(tabId!)
      })

      expect(callback1).not.toHaveBeenCalled()
      expect(callback2).toHaveBeenCalledWith(tabId)
    })
  })

  describe('Active Tab Tracking', () => {
    test('should track active tab through multiple switches', () => {
      const { result } = renderHook(() => useTabs(), { wrapper })

      const tabIds: (string | null)[] = ['default']
      act(() => {
        tabIds.push(result.current.createTab())
        tabIds.push(result.current.createTab())
        tabIds.push(result.current.createTab())
      })

      // Current active should be the last created tab
      expect(result.current.activeTabId).toBe(tabIds[3])

      // Switch through tabs
      act(() => {
        result.current.switchTab(tabIds[0]!)
      })
      expect(result.current.activeTabId).toBe(tabIds[0])

      act(() => {
        result.current.switchTab(tabIds[2]!)
      })
      expect(result.current.activeTabId).toBe(tabIds[2])

      act(() => {
        result.current.switchTab(tabIds[1]!)
      })
      expect(result.current.activeTabId).toBe(tabIds[1])
    })
  })
})
