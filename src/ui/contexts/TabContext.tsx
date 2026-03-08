/* eslint-disable react-refresh/only-export-components */
/**
 * Tab context — manages the list of open tabs and the active tab ID.
 *
 * Owns the list of open tabs, the active tab ID, and a persistent per-tab
 * snapshot registry that survives route changes.
 */
import React, { createContext, useContext, useState, useCallback, useRef } from 'react';
import type { TabInfo, QueueItem, TabSnapshot } from '../types';

const MAX_TABS = 10;

interface TabContextValue {
  /** All open tabs (ordered). */
  tabs: TabInfo[];
  /** Currently visible tab. */
  activeTabId: string;
  /** Per-tab queue items from the backend. */
  queueMap: Record<string, QueueItem[]>;

  /** Create a new tab. Returns the new tab's ID. */
  createTab: () => string | null;
  /** Close a tab by ID. Switches to the previous tab (or first remaining). */
  closeTab: (tabId: string) => void;
  /** Switch to a specific tab by ID. */
  switchTab: (tabId: string) => void;
  /** Rename a tab. */
  updateTabTitle: (tabId: string, title: string) => void;
  /** Update the queue items for a tab (called from WS handler). */
  setQueueItems: (tabId: string, items: QueueItem[]) => void;
  /** Read a persisted snapshot for a tab. */
  getTabSnapshot: (tabId: string) => TabSnapshot | undefined;
  /** Persist a snapshot for a tab. */
  setTabSnapshot: (tabId: string, snapshot: TabSnapshot) => void;
  /** Remove a persisted snapshot for a tab. */
  deleteTabSnapshot: (tabId: string) => void;

  /**
   * Register a handler that is called BEFORE the active tab actually changes.
   * This lets App.tsx snapshot the outgoing tab's state.
   */
  registerBeforeSwitch: (fn: (oldTabId: string) => void) => () => void;
  /**
   * Register a handler that is called AFTER the active tab has changed.
   * This lets App.tsx restore the incoming tab's state.
   */
  registerAfterSwitch: (fn: (newTabId: string) => void) => () => void;
  /**
   * Register a handler called when a tab is closed.
   * This lets App.tsx clean up the state registry entry.
   */
  registerOnTabClosed: (fn: (closedTabId: string) => void) => () => void;
}

const TabContext = createContext<TabContextValue | null>(null);

let _tabCounter = 0;

export function TabProvider({ children }: { children: React.ReactNode }) {
  const [tabs, setTabs] = useState<TabInfo[]>([{ id: 'default', title: 'Chat' }]);
  const [activeTabId, setActiveTabId] = useState('default');
  const [queueMap, setQueueMap] = useState<Record<string, QueueItem[]>>({});

  const beforeSwitchRef = useRef<((oldTabId: string) => void) | null>(null);
  const afterSwitchRef = useRef<((newTabId: string) => void) | null>(null);
  const onTabClosedRef = useRef<((closedTabId: string) => void) | null>(null);
  const tabSnapshotsRef = useRef<Map<string, TabSnapshot>>(new Map());

  const registerBeforeSwitch = useCallback((fn: (oldTabId: string) => void) => {
    beforeSwitchRef.current = fn;
    return () => {
      if (beforeSwitchRef.current === fn) {
        beforeSwitchRef.current = null;
      }
    };
  }, []);

  const registerAfterSwitch = useCallback((fn: (newTabId: string) => void) => {
    afterSwitchRef.current = fn;
    return () => {
      if (afterSwitchRef.current === fn) {
        afterSwitchRef.current = null;
      }
    };
  }, []);

  const registerOnTabClosed = useCallback((fn: (closedTabId: string) => void) => {
    onTabClosedRef.current = fn;
    return () => {
      if (onTabClosedRef.current === fn) {
        onTabClosedRef.current = null;
      }
    };
  }, []);

  const getTabSnapshot = useCallback((tabId: string) => {
    return tabSnapshotsRef.current.get(tabId);
  }, []);

  const setTabSnapshot = useCallback((tabId: string, snapshot: TabSnapshot) => {
    tabSnapshotsRef.current.set(tabId, snapshot);
  }, []);

  const deleteTabSnapshot = useCallback((tabId: string) => {
    tabSnapshotsRef.current.delete(tabId);
  }, []);

  const createTab = useCallback((): string | null => {
    if (tabs.length >= MAX_TABS) return null;
    _tabCounter += 1;
    const id = `tab-${Date.now()}-${_tabCounter}`;
    setTabs(prev => [...prev, { id, title: 'New Chat' }]);
    // Switch to the new tab
    beforeSwitchRef.current?.(activeTabId);
    setActiveTabId(id);
    // Let App.tsx know to initialise state for this tab
    afterSwitchRef.current?.(id);
    return id;
  }, [tabs.length, activeTabId]);

  const closeTab = useCallback(
    (tabId: string) => {
      // Cannot close the last tab
      if (tabs.length <= 1) return;

      const idx = tabs.findIndex(t => t.id === tabId);
      const newTabs = tabs.filter(t => t.id !== tabId);
      setTabs(newTabs);

      // Clean up queue data
      setQueueMap(prev => {
        const next = { ...prev };
        delete next[tabId];
        return next;
      });

      // Notify App.tsx to clean up state registry
      onTabClosedRef.current?.(tabId);

      if (tabId === activeTabId) {
        // Switch to the nearest remaining tab
        const newIdx = Math.min(idx, newTabs.length - 1);
        const newActiveId = newTabs[newIdx].id;
        setActiveTabId(newActiveId);
        afterSwitchRef.current?.(newActiveId);
      }
    },
    [tabs, activeTabId],
  );

  const switchTab = useCallback(
    (tabId: string) => {
      if (tabId === activeTabId) return;
      if (!tabs.some(t => t.id === tabId)) return;
      beforeSwitchRef.current?.(activeTabId);
      setActiveTabId(tabId);
      afterSwitchRef.current?.(tabId);
    },
    [activeTabId, tabs],
  );

  const updateTabTitle = useCallback((tabId: string, title: string) => {
    setTabs(prev => prev.map(t => (t.id === tabId ? { ...t, title } : t)));
  }, []);

  const setQueueItems = useCallback((tabId: string, items: QueueItem[]) => {
    setQueueMap(prev => ({ ...prev, [tabId]: items }));
  }, []);

  return (
    <TabContext.Provider
      value={{
        tabs,
        activeTabId,
        queueMap,
        createTab,
        closeTab,
        switchTab,
        updateTabTitle,
        setQueueItems,
        getTabSnapshot,
        setTabSnapshot,
        deleteTabSnapshot,
        registerBeforeSwitch,
        registerAfterSwitch,
        registerOnTabClosed,
      }}
    >
      {children}
    </TabContext.Provider>
  );
}

export function useTabs(): TabContextValue {
  const ctx = useContext(TabContext);
  if (!ctx) throw new Error('useTabs must be used within <TabProvider>');
  return ctx;
}
