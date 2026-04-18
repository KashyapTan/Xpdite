import { describe, expect, test } from 'vitest';

import { createBootShellDataUrl } from './bootShellHtml.js';

describe('createBootShellDataUrl', () => {
  test('returns an encoded boot shell document with retry and IPC hooks', () => {
    const url = createBootShellDataUrl();

    expect(url.startsWith('data:text/html;charset=UTF-8,')).toBe(true);

    const html = decodeURIComponent(url.slice('data:text/html;charset=UTF-8,'.length));
    expect(html).toContain('id="retryButton"');
    expect(html).toContain("window.electronAPI.getBootState");
    expect(html).toContain("phaseLabels");
    expect(html).toContain("Retry startup");
  });
});
