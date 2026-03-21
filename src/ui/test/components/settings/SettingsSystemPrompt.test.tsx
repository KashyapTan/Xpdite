import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsSystemPrompt from '../../../components/settings/SettingsSystemPrompt';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getSystemPrompt: vi.fn(),
    setSystemPrompt: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsSystemPrompt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getSystemPrompt.mockResolvedValue({
      template: 'Default template',
      is_custom: false,
    });
    mockedApi.setSystemPrompt.mockResolvedValue(undefined);
  });

  test('loads and renders prompt template', async () => {
    render(<SettingsSystemPrompt />);
    const textarea = (await screen.findByRole('textbox')) as HTMLTextAreaElement;
    expect(textarea.value).toBe('Default template');
  });

  test('saves custom template and shows badge', async () => {
    render(<SettingsSystemPrompt />);

    const textarea = (await screen.findByRole('textbox')) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'My custom prompt' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mockedApi.setSystemPrompt).toHaveBeenCalledWith('My custom prompt');
      expect(screen.getByText('Custom')).toBeInTheDocument();
      expect(screen.getByText('Saved')).toBeInTheDocument();
    });
  });

  test('shows error text when save fails', async () => {
    mockedApi.setSystemPrompt.mockRejectedValue(new Error('save failed'));

    render(<SettingsSystemPrompt />);
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Save failed.')).toBeInTheDocument();
  });

  test('resets to default prompt', async () => {
    mockedApi.getSystemPrompt
      .mockResolvedValueOnce({ template: 'Custom template', is_custom: true })
      .mockResolvedValueOnce({ template: 'Factory default', is_custom: false });

    render(<SettingsSystemPrompt />);
    fireEvent.click(await screen.findByRole('button', { name: 'Reset to Default' }));

    await waitFor(() => {
      expect(mockedApi.setSystemPrompt).toHaveBeenCalledWith('');
      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
      expect(textarea.value).toBe('Factory default');
    });
  });
});

