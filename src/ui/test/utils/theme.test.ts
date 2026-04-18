import { describe, expect, test } from 'vitest';

import { getTerminalTheme, readCssVariable } from '../../utils/theme';

describe('theme utils', () => {
  test('returns the fallback when a CSS variable is unset', () => {
    document.documentElement.style.removeProperty('--color-missing');

    expect(readCssVariable('--color-missing', '#abc123')).toBe('#abc123');
  });

  test('reads CSS variables from the root element', () => {
    document.documentElement.style.setProperty('--color-terminal-background', '#010203');
    document.documentElement.style.setProperty('--color-terminal-foreground', '#fefefe');
    document.documentElement.style.setProperty('--color-terminal-cursor', '#ff00ff');
    document.documentElement.style.setProperty('--color-terminal-selection', 'rgba(0, 0, 0, 0.5)');

    expect(getTerminalTheme()).toEqual({
      background: '#010203',
      foreground: '#fefefe',
      cursor: '#ff00ff',
      selectionBackground: 'rgba(0, 0, 0, 0.5)',
    });
  });
});
