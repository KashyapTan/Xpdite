/**
 * Keyboard shortcuts for tab management.
 *
 * Shortcuts:
 * - Ctrl+T (Cmd+T on Mac): Create a new tab
 * - Ctrl+W (Cmd+W on Mac): Close the current tab (only if >1 tab open)
 * - Ctrl+Tab: Switch to the next tab (cycles to first tab from last)
 * - Ctrl+Shift+Tab: Switch to the previous tab (cycles to last tab from first)
 *
 * These shortcuts only fire when the app window is focused (standard browser behavior).
 */
import { useEffect } from 'react';
import { useTabs } from '../contexts/TabContext';

export function useTabKeyboardShortcuts(): void {
  const { tabs, activeTabId, createTab, closeTab, switchTab } = useTabs();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isCtrlOrCmd = e.ctrlKey || e.metaKey;

      // Ctrl+T → New tab
      if (isCtrlOrCmd && e.key.toLowerCase() === 't' && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        createTab();
        return;
      }

      // Ctrl+W → Close current tab (only if more than 1 tab)
      if (isCtrlOrCmd && e.key.toLowerCase() === 'w' && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        if (tabs.length > 1) {
          closeTab(activeTabId);
        }
        // If only 1 tab, do nothing (preventDefault already prevents window closing)
        return;
      }

      // Ctrl+Tab → Next tab (cycle right)
      if (isCtrlOrCmd && e.key === 'Tab' && !e.shiftKey) {
        e.preventDefault();
        const currentIdx = tabs.findIndex(t => t.id === activeTabId);
        const nextIdx = (currentIdx + 1) % tabs.length;
        switchTab(tabs[nextIdx].id);
        return;
      }

      // Ctrl+Shift+Tab → Previous tab (cycle left)
      if (isCtrlOrCmd && e.key === 'Tab' && e.shiftKey) {
        e.preventDefault();
        const currentIdx = tabs.findIndex(t => t.id === activeTabId);
        const prevIdx = (currentIdx - 1 + tabs.length) % tabs.length;
        switchTab(tabs[prevIdx].id);
        return;
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [tabs, activeTabId, createTab, closeTab, switchTab]);
}
