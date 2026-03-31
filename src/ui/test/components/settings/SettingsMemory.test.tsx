import { beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsMemory from '../../../components/settings/SettingsMemory';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getMemorySettings: vi.fn(),
    setMemorySettings: vi.fn(),
    listMemories: vi.fn(),
    getMemory: vi.fn(),
    updateMemory: vi.fn(),
    deleteMemory: vi.fn(),
    clearAllMemories: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

const memorySummaries = [
  {
    path: 'profile/user_profile.md',
    folder: 'profile',
    title: 'User Profile',
    category: 'profile',
    importance: 1,
    tags: ['profile'],
    abstract: 'Stable facts about the user.',
    created: '2026-03-29T10:00:00.000Z',
    updated: '2026-03-29T10:00:00.000Z',
    last_accessed: '2026-03-29T10:00:00.000Z',
  },
  {
    path: 'procedural/sqlite_fix.md',
    folder: 'procedural',
    title: 'SQLite Fix',
    category: 'procedural',
    importance: 0.85,
    tags: ['sqlite'],
    abstract: 'Reusable SQLite fix.',
    created: '2026-03-29T10:00:00.000Z',
    updated: '2026-03-29T10:00:00.000Z',
    last_accessed: '2026-03-29T10:00:00.000Z',
  },
];

const sqliteDetail = {
  ...memorySummaries[1],
  body: 'Always use a per-request SQLite connection.',
  raw_text: '---\n...',
};

describe('SettingsMemory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getMemorySettings.mockResolvedValue({ profile_auto_inject: true });
    mockedApi.setMemorySettings.mockResolvedValue(undefined);
    mockedApi.listMemories.mockResolvedValue(memorySummaries);
    mockedApi.getMemory.mockResolvedValue(sqliteDetail);
    mockedApi.updateMemory.mockResolvedValue(sqliteDetail);
    mockedApi.deleteMemory.mockResolvedValue(undefined);
    mockedApi.clearAllMemories.mockResolvedValue({ success: true, deleted_count: 2 });
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  test('loads grouped memories and toggles profile auto-inject', async () => {
    render(<SettingsMemory />);

    expect(await screen.findByText('User Profile')).toBeInTheDocument();
    expect(screen.getByText('SQLite Fix')).toBeInTheDocument();
    expect(
      screen.getByText(/That memory is sent to the active model, including cloud providers/i),
    ).toBeInTheDocument();

    const toggle = screen.getByLabelText('Profile auto-inject') as HTMLInputElement;
    expect(toggle.checked).toBe(true);

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockedApi.setMemorySettings).toHaveBeenCalledWith({ profile_auto_inject: false });
    });
  });

  test('still renders memories when loading settings fails', async () => {
    mockedApi.getMemorySettings.mockRejectedValueOnce(new Error('settings unavailable'));

    render(<SettingsMemory />);

    expect(await screen.findByText('User Profile')).toBeInTheDocument();
    expect(screen.getByText('SQLite Fix')).toBeInTheDocument();
    expect(screen.getByText('settings unavailable')).toBeInTheDocument();

    const toggle = screen.getByLabelText('Profile auto-inject') as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(toggle.disabled).toBe(true);
  });

  test('renders the memory browser even while settings are still loading', async () => {
    mockedApi.getMemorySettings.mockReturnValue(
      new Promise(() => {}),
    );

    render(<SettingsMemory />);

    expect(await screen.findByText('User Profile')).toBeInTheDocument();
    expect(screen.getByText('SQLite Fix')).toBeInTheDocument();
    expect(screen.getByLabelText('Profile auto-inject')).toBeDisabled();
  });

  test('selects a memory, edits fields, and saves', async () => {
    render(<SettingsMemory />);

    fireEvent.click(await screen.findByText('SQLite Fix'));

    await waitFor(() => {
      expect(mockedApi.getMemory).toHaveBeenCalledWith('procedural/sqlite_fix.md');
    });

    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'SQLite Fix Updated' } });
    fireEvent.change(screen.getByLabelText('Abstract'), { target: { value: 'Updated reusable fix.' } });
    fireEvent.change(screen.getByLabelText('Body'), { target: { value: 'Use a fresh connection for every request.' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mockedApi.updateMemory).toHaveBeenCalledWith({
        path: 'procedural/sqlite_fix.md',
        title: 'SQLite Fix Updated',
        category: 'procedural',
        importance: 0.85,
        tags: ['sqlite'],
        abstract: 'Updated reusable fix.',
        body: 'Use a fresh connection for every request.',
      });
    });
  });

  test('rolls back the profile toggle when saving settings fails', async () => {
    mockedApi.setMemorySettings.mockRejectedValueOnce(new Error('save failed'));
    render(<SettingsMemory />);

    const toggle = await screen.findByLabelText('Profile auto-inject') as HTMLInputElement;
    expect(toggle.checked).toBe(true);

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockedApi.setMemorySettings).toHaveBeenCalledWith({ profile_auto_inject: false });
    });

    expect(toggle.checked).toBe(true);
    expect(screen.getByText('save failed')).toBeInTheDocument();
  });

  test('disables the profile toggle while saving settings', async () => {
    let resolveSave: (() => void) | undefined;
    mockedApi.setMemorySettings.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveSave = resolve;
      }),
    );

    render(<SettingsMemory />);

    const toggle = await screen.findByLabelText('Profile auto-inject') as HTMLInputElement;
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockedApi.setMemorySettings).toHaveBeenCalledWith({ profile_auto_inject: false });
    });

    expect(toggle.disabled).toBe(true);
    fireEvent.click(toggle);
    expect(mockedApi.setMemorySettings).toHaveBeenCalledTimes(1);

    resolveSave?.();
    await waitFor(() => {
      expect(toggle.disabled).toBe(false);
    });
  });

  test('deletes selected memory and clears all memories after confirmation', async () => {
    render(<SettingsMemory />);

    fireEvent.click(await screen.findByText('SQLite Fix'));
    await screen.findByDisplayValue('SQLite Fix');

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => {
      expect(mockedApi.deleteMemory).toHaveBeenCalledWith('procedural/sqlite_fix.md');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Clear All Memories' }));
    await waitFor(() => {
      expect(mockedApi.clearAllMemories).toHaveBeenCalled();
    });
  });

  test('does not delete when confirmation is cancelled', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    render(<SettingsMemory />);

    fireEvent.click(await screen.findByText('SQLite Fix'));
    await screen.findByDisplayValue('SQLite Fix');

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(mockedApi.deleteMemory).not.toHaveBeenCalled();
  });

  test('disables destructive buttons while requests are in flight', async () => {
    let resolveDelete: (() => void) | undefined;
    let resolveClear: ((value: { success: boolean; deleted_count: number }) => void) | undefined;

    mockedApi.deleteMemory.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveDelete = resolve;
      }),
    );
    mockedApi.clearAllMemories.mockReturnValue(
      new Promise<{ success: boolean; deleted_count: number }>((resolve) => {
        resolveClear = resolve;
      }),
    );

    render(<SettingsMemory />);

    fireEvent.click(await screen.findByText('SQLite Fix'));
    await screen.findByDisplayValue('SQLite Fix');

    const deleteButton = screen.getByRole('button', { name: 'Delete' });
    fireEvent.click(deleteButton);

    expect(mockedApi.deleteMemory).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Deleting...' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Deleting...' }));
    expect(mockedApi.deleteMemory).toHaveBeenCalledTimes(1);

    resolveDelete?.();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled();
    });

    const clearButton = screen.getByRole('button', { name: 'Clear All Memories' });
    fireEvent.click(clearButton);

    expect(mockedApi.clearAllMemories).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Clearing...' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Clearing...' }));
    expect(mockedApi.clearAllMemories).toHaveBeenCalledTimes(1);

    resolveClear?.({ success: true, deleted_count: 2 });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Clear All Memories' })).toBeEnabled();
    });
  });
});
