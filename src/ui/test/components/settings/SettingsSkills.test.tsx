import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsSkills from '../../../components/settings/SettingsSkills';
import { api } from '../../../services/api';
import type { Skill } from '../../../types';

vi.mock('../../../services/api', () => ({
  api: {
    skillsApi: {
      getAll: vi.fn(),
      getContent: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      toggle: vi.fn(),
      delete: vi.fn(),
    },
  },
}));

const mockedApi = vi.mocked(api);

const builtinSkill: Skill = {
  name: 'terminal-safety',
  description: 'Terminal safety defaults',
  slash_command: 'terminal',
  trigger_servers: ['terminal'],
  version: '1.0.0',
  source: 'builtin',
  enabled: true,
  overridden_by_user: false,
  folder_path: 'builtin/terminal-safety',
};

const userSkill: Skill = {
  name: 'my-custom-skill',
  description: 'My custom skill',
  slash_command: 'custom',
  trigger_servers: ['filesystem'],
  version: '0.1.0',
  source: 'user',
  enabled: true,
  overridden_by_user: false,
  folder_path: 'user/my-custom-skill',
};

describe('SettingsSkills', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.skillsApi.getAll.mockResolvedValue([builtinSkill, userSkill]);
    mockedApi.skillsApi.getContent.mockResolvedValue('Existing content');
    mockedApi.skillsApi.create.mockResolvedValue(undefined);
    mockedApi.skillsApi.update.mockResolvedValue(undefined);
    mockedApi.skillsApi.toggle.mockResolvedValue(undefined);
    mockedApi.skillsApi.delete.mockResolvedValue(undefined);
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test('loads and renders skill cards', async () => {
    render(<SettingsSkills />);

    expect(await screen.findByText('terminal-safety')).toBeInTheDocument();
    expect(screen.getByText('my-custom-skill')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add Custom Skill' })).toBeInTheDocument();
  });

  test('toggles a skill and handles toggle errors', async () => {
    render(<SettingsSkills />);

    const toggle = await screen.findByLabelText('Toggle my-custom-skill');
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(mockedApi.skillsApi.toggle).toHaveBeenCalledWith('my-custom-skill', false);
    });

    mockedApi.skillsApi.toggle.mockRejectedValueOnce(new Error('Toggle failed'));
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(console.error).toHaveBeenCalledWith('Failed to toggle skill', expect.any(Error));
      expect(window.alert).toHaveBeenCalledWith('Toggle failed');
    });
  });

  test('validates required fields in create editor', async () => {
    render(<SettingsSkills />);

    fireEvent.click(await screen.findByRole('button', { name: 'Add Custom Skill' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));

    expect(await screen.findByText('Description and content are required.')).toBeInTheDocument();
  });

  test('creates a skill with sanitized name/command and parsed trigger servers', async () => {
    render(<SettingsSkills />);

    fireEvent.click(await screen.findByRole('button', { name: 'Add Custom Skill' }));

    fireEvent.change(screen.getByPlaceholderText('e.g. my-custom-skill'), {
      target: { value: 'My Skill!!' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. Guidance for terminal command execution'), {
      target: { value: 'Useful skill' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. terminal'), {
      target: { value: '/quick-help' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. terminal, filesystem'), {
      target: { value: 'terminal, filesystem, ,  ' },
    });
    fireEvent.change(screen.getByPlaceholderText('Instructions to inject into the system prompt...'), {
      target: { value: 'Do useful things' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));

    await waitFor(() => {
      expect(mockedApi.skillsApi.create).toHaveBeenCalledWith({
        name: 'myskill',
        description: 'Useful skill',
        slash_command: 'quick-help',
        content: 'Do useful things',
        trigger_servers: ['terminal', 'filesystem'],
      });
      expect(mockedApi.skillsApi.getAll).toHaveBeenCalledTimes(2);
      expect(screen.getByRole('button', { name: 'Add Custom Skill' })).toBeInTheDocument();
    });
  });

  test('requires name for new skills after description/content are provided', async () => {
    render(<SettingsSkills />);

    fireEvent.click(await screen.findByRole('button', { name: 'Add Custom Skill' }));
    fireEvent.change(screen.getByPlaceholderText('e.g. Guidance for terminal command execution'), {
      target: { value: 'Named skill' },
    });
    fireEvent.change(screen.getByPlaceholderText('Instructions to inject into the system prompt...'), {
      target: { value: 'Skill body' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));

    expect(await screen.findByText('Name is required for new skills.')).toBeInTheDocument();
  });

  test('edits and deletes user skills with confirm branch coverage', async () => {
    render(<SettingsSkills />);

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    await waitFor(() => {
      expect(mockedApi.skillsApi.getContent).toHaveBeenCalledWith('my-custom-skill');
    });

    fireEvent.change(screen.getByDisplayValue('My custom skill'), {
      target: { value: 'Edited description' },
    });
    fireEvent.change(screen.getByPlaceholderText('e.g. terminal, filesystem'), {
      target: { value: 'filesystem, terminal' },
    });
    fireEvent.change(screen.getByDisplayValue('Existing content'), {
      target: { value: 'Edited content' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save Skill' }));

    await waitFor(() => {
      expect(mockedApi.skillsApi.update).toHaveBeenCalledWith('my-custom-skill', {
        description: 'Edited description',
        slash_command: 'custom',
        content: 'Edited content',
        trigger_servers: ['filesystem', 'terminal'],
      });
    });

    vi.mocked(window.confirm).mockReturnValueOnce(false);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(mockedApi.skillsApi.delete).not.toHaveBeenCalled();

    vi.mocked(window.confirm).mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(mockedApi.skillsApi.delete).toHaveBeenCalledWith('my-custom-skill');
    });
  });
});

