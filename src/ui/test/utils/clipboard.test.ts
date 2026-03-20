import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { copyToClipboard } from '../../utils/clipboard';

describe('copyToClipboard', () => {
  const originalClipboard = navigator.clipboard;
  const originalExecCommandDescriptor = Object.getOwnPropertyDescriptor(document, 'execCommand');
  let execCommandMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.restoreAllMocks();
    execCommandMock = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      value: execCommandMock,
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'clipboard', {
      value: originalClipboard,
      configurable: true,
      writable: true,
    });
    if (originalExecCommandDescriptor) {
      Object.defineProperty(document, 'execCommand', originalExecCommandDescriptor);
    } else {
      delete (document as Document & { execCommand?: unknown }).execCommand;
    }
  });

  test('uses navigator clipboard when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    await copyToClipboard('hello world');

    expect(writeText).toHaveBeenCalledWith('hello world');
    expect(execCommandMock).not.toHaveBeenCalled();
  });

  test('falls back to textarea + execCommand when clipboard write fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('Permission denied'));
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    await copyToClipboard('fallback text');

    expect(writeText).toHaveBeenCalledWith('fallback text');
    expect(execCommandMock).toHaveBeenCalledWith('copy');
    expect(errorSpy).toHaveBeenCalled();
    expect(document.querySelectorAll('textarea')).toHaveLength(0);
  });

  test('logs fallback failure but still cleans up textarea', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('clipboard failed'));
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });

    execCommandMock.mockImplementation(() => {
      throw new Error('exec failed');
    });
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    await copyToClipboard('double failure');

    expect(execCommandMock).toHaveBeenCalledWith('copy');
    expect(errorSpy).toHaveBeenCalledTimes(2);
    expect(document.querySelectorAll('textarea')).toHaveLength(0);
  });
});

