export function readCssVariable(name: string, fallback: string): string {
  if (typeof window === 'undefined') {
    return fallback;
  }

  const value = window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function getTerminalTheme() {
  return {
    background: readCssVariable('--color-terminal-background', '#111111'),
    foreground: readCssVariable('--color-terminal-foreground', 'rgba(255, 255, 255, 0.92)'),
    cursor: readCssVariable('--color-terminal-cursor', 'rgba(255, 255, 255, 0.92)'),
    selectionBackground: readCssVariable('--color-terminal-selection', 'rgba(255, 255, 255, 0.2)'),
  };
}
