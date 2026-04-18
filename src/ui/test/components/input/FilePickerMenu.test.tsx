import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import FilePickerMenu from '../../../components/input/FilePickerMenu';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    browseFiles: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('FilePickerMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.browseFiles.mockResolvedValue({
      entries: [
        {
          name: 'README.md',
          path: '/repo/README.md',
          relative_path: 'README.md',
          is_directory: false,
          size: 1536,
          extension: 'md',
        },
        {
          name: 'src',
          path: '/repo/src',
          relative_path: 'src',
          is_directory: true,
          size: null,
          extension: null,
        },
      ],
    });
  });

  test('loads entries, forwards selection/hover changes, and closes on escape', async () => {
    const onClose = vi.fn();
    const onEntriesChange = vi.fn();
    const onSelect = vi.fn();
    const onSelectedIndexChange = vi.fn();

    render(
      <FilePickerMenu
        searchQuery="read"
        position={{ top: 0, left: 32 }}
        selectedIndex={0}
        onClose={onClose}
        onEntriesChange={onEntriesChange}
        onSelect={onSelect}
        onSelectedIndexChange={onSelectedIndexChange}
      />,
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 110));
    });

    const readmeButton = await screen.findByRole('button', { name: /README\.md/i });
    expect(readmeButton).toBeInTheDocument();
    expect(mockedApi.browseFiles).toHaveBeenCalledWith('read');
    expect(onEntriesChange).toHaveBeenCalledWith([
      expect.objectContaining({ name: 'README.md' }),
      expect.objectContaining({ name: 'src' }),
    ]);
    expect(onSelectedIndexChange).toHaveBeenCalledWith(0);
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();

    fireEvent.mouseEnter(screen.getByRole('button', { name: /src/i }));
    expect(onSelectedIndexChange).toHaveBeenCalledWith(1);

    fireEvent.click(readmeButton);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ name: 'README.md' }));

    fireEvent.keyDown(screen.getByText('↑↓ navigate').closest('.file-picker-menu') as Element, {
      key: 'Escape',
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('renders API errors and empty-state fallbacks', async () => {
    mockedApi.browseFiles.mockRejectedValueOnce(new Error('Browse failed'));

    render(
      <FilePickerMenu
        searchQuery="config"
        position={{ top: 0, left: 16 }}
        selectedIndex={0}
        onClose={vi.fn()}
        onSelect={vi.fn()}
        onSelectedIndexChange={vi.fn()}
      />,
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 110));
    });

    expect(await screen.findByText('Browse failed')).toBeInTheDocument();

    mockedApi.browseFiles.mockResolvedValueOnce({ entries: [] });

    document.body.innerHTML = '';
    render(
      <FilePickerMenu
        searchQuery=""
        position={{ top: 0, left: 16 }}
        selectedIndex={0}
        onClose={vi.fn()}
        onSelect={vi.fn()}
        onSelectedIndexChange={vi.fn()}
      />,
    );

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 110));
    });

    await waitFor(() => {
      expect(screen.getByText('Type after @ to search files')).toBeInTheDocument();
    });
  });
});
