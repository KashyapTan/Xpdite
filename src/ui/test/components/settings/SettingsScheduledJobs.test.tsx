import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import SettingsScheduledJobs from '../../../components/settings/SettingsScheduledJobs';
import { api } from '../../../services/api';

type ChannelBridgeStatusCallback = (platforms: unknown) => void;

let channelBridgeStatusCallback: ChannelBridgeStatusCallback | null = null;

vi.mock('../../../services/api', () => ({
  api: {
    deleteScheduledJob: vi.fn(),
    getMobileChannelsConfig: vi.fn(),
    getScheduledJobs: vi.fn(),
    pauseScheduledJob: vi.fn(),
    resumeScheduledJob: vi.fn(),
    runScheduledJobNow: vi.fn(),
    updateScheduledJob: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsScheduledJobs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    channelBridgeStatusCallback = null;
    window.electronAPI = {
      ...window.electronAPI,
      getChannelBridgeStatus: vi.fn(async () => ({
        platforms: [{ platform: 'telegram', status: 'connected' }],
      })),
      onChannelBridgeStatus: vi.fn((callback: ChannelBridgeStatusCallback) => {
        channelBridgeStatusCallback = callback;
        return () => {
          channelBridgeStatusCallback = null;
        };
      }),
    };
    mockedApi.getScheduledJobs.mockResolvedValue({
      jobs: [
        {
          id: 'job-1',
          name: 'Morning Brief',
          cron_expression: '0 9 * * 1,3',
          instruction: 'Summarize the inbox',
          model: 'gpt-4o',
          timezone: 'America/New_York',
          delivery_platform: null,
          delivery_sender_id: null,
          enabled: true,
          is_one_shot: false,
          created_at: 1_700_000_000,
          last_run_at: 1_700_000_100,
          next_run_at: 1_700_000_200,
          run_count: 2,
          missed: false,
        },
      ],
    });
    mockedApi.getMobileChannelsConfig.mockResolvedValue({
      platforms: {},
    });
    mockedApi.pauseScheduledJob.mockResolvedValue({ id: 'job-1', name: 'Morning Brief', enabled: false });
    mockedApi.resumeScheduledJob.mockResolvedValue({ id: 'job-1', name: 'Morning Brief', enabled: true, next_run_at: 1_700_000_200 });
    mockedApi.runScheduledJobNow.mockResolvedValue({ success: true, conversation_id: 'conversation-1', job_name: 'Morning Brief' });
    mockedApi.deleteScheduledJob.mockResolvedValue(undefined);
    mockedApi.updateScheduledJob.mockResolvedValue({
      id: 'job-1',
      name: 'Morning Brief',
      cron_expression: '0 9 * * 1,3',
      instruction: 'Summarize the inbox',
      timezone: 'America/New_York',
      model: 'gpt-4o',
      enabled: true,
      is_one_shot: false,
    });
  });

  test('merges initial bridge status, adds new connected platforms from live updates, and saves forwarding', async () => {
    render(<SettingsScheduledJobs />);

    fireEvent.click(await screen.findByText('Morning Brief'));
    fireEvent.click(screen.getByRole('button', { name: 'Add Forwarding' }));

    expect(await screen.findByRole('option', { name: 'Telegram' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'WhatsApp' })).not.toBeInTheDocument();

    await act(async () => {
      channelBridgeStatusCallback?.([{ platform: 'whatsapp', status: 'connected' }]);
    });

    expect(await screen.findByRole('option', { name: 'WhatsApp' })).toBeInTheDocument();

    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: 'whatsapp' },
    });
    fireEvent.change(screen.getByPlaceholderText('+1234567890'), {
      target: { value: '+15551234567' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(mockedApi.updateScheduledJob).toHaveBeenCalledWith('job-1', {
        delivery_platform: 'whatsapp',
        delivery_sender_id: '+15551234567',
      });
    });
  });

  test('runs, pauses, resumes, and deletes jobs with confirmation', async () => {
    const activeJob = {
      id: 'job-1',
      name: 'Morning Brief',
      cron_expression: '0 9 * * *',
      instruction: 'Summarize the inbox',
      model: null,
      timezone: 'America/New_York',
      delivery_platform: null,
      delivery_sender_id: null,
      enabled: true,
      is_one_shot: false,
      created_at: 1_700_000_000,
      last_run_at: null,
      next_run_at: 1_700_000_200,
      run_count: 0,
      missed: false,
    };
    const pausedJob = {
      ...activeJob,
      enabled: false,
    };

    mockedApi.getScheduledJobs
      .mockResolvedValueOnce({
        jobs: [activeJob],
      })
      .mockResolvedValueOnce({
        jobs: [pausedJob],
      })
      .mockResolvedValueOnce({
        jobs: [pausedJob],
      })
      .mockResolvedValue({
        jobs: [],
      });

    render(<SettingsScheduledJobs />);

    fireEvent.click(await screen.findByText('Morning Brief'));
    fireEvent.click(screen.getByTitle('Pause task'));

    await waitFor(() => {
      expect(mockedApi.pauseScheduledJob).toHaveBeenCalledWith('job-1');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Run Now' }));
    await waitFor(() => {
      expect(mockedApi.runScheduledJobNow).toHaveBeenCalledWith('job-1');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => {
      expect(mockedApi.deleteScheduledJob).toHaveBeenCalledWith('job-1');
    });
    expect(screen.getByText('No scheduled tasks yet')).toBeInTheDocument();
  });

  test('shows fetch errors and allows dismissing action errors', async () => {
    mockedApi.getScheduledJobs.mockRejectedValueOnce(new Error('Scheduler unavailable'));

    render(<SettingsScheduledJobs />);
    expect(await screen.findByText('Failed to load scheduled tasks')).toBeInTheDocument();

    mockedApi.getScheduledJobs.mockResolvedValue({
      jobs: [
        {
          id: 'job-1',
          name: 'Morning Brief',
          cron_expression: '0 9 * * *',
          instruction: 'Summarize the inbox',
          model: null,
          timezone: 'America/New_York',
          delivery_platform: null,
          delivery_sender_id: null,
          enabled: true,
          is_one_shot: false,
          created_at: 1_700_000_000,
          last_run_at: null,
          next_run_at: 1_700_000_200,
          run_count: 0,
          missed: false,
        },
      ],
    });
    mockedApi.pauseScheduledJob.mockRejectedValueOnce(new Error('Pause failed'));
    document.body.innerHTML = '';
    render(<SettingsScheduledJobs />);
    fireEvent.click(await screen.findByText('Morning Brief'));
    fireEvent.click(screen.getByTitle('Pause task'));

    expect(await screen.findByText('Failed to toggle task')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByText('Failed to toggle task')).not.toBeInTheDocument();
  });
});
