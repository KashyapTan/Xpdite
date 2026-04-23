import { describe, expect, test, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import MeetingRecordingDetail from '../../pages/MeetingRecordingDetail';

const { wsSendMock, wsSubscribeMock, setMiniMock, getEnabledModelsMock } = vi.hoisted(() => ({
  wsSendMock: vi.fn(),
  wsSubscribeMock: vi.fn(),
  setMiniMock: vi.fn(),
  getEnabledModelsMock: vi.fn(),
}));

type WsMessage = {
  type: string;
  content?: unknown;
};

let wsHandler: ((msg: WsMessage) => void) | null = null;

async function dispatchWsMessage(message: WsMessage) {
  await act(async () => {
    wsHandler?.(message);
  });
}

vi.mock('../../components/TitleBar', () => ({
  default: () => <div data-testid="title-bar">title</div>,
}));

vi.mock('../../components/icons/AppIcons', () => ({
  CalendarIcon: () => <svg data-testid="icon-calendar" />,
  CheckIcon: () => <svg data-testid="icon-check" />,
  ClipboardListIcon: () => <svg data-testid="icon-clipboard" />,
  HourglassIcon: () => <svg data-testid="icon-hourglass" />,
  MailIcon: () => <svg data-testid="icon-mail" />,
  RecordIcon: () => <svg data-testid="icon-record" />,
  XIcon: () => <svg data-testid="icon-x" />,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useParams: () => ({ id: 'rec-1' }),
    useOutletContext: () => ({ setMini: setMiniMock }),
  };
});

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: wsSendMock,
    subscribe: wsSubscribeMock,
  }),
}));

vi.mock('../../services/api', () => ({
  api: {
    getEnabledModels: getEnabledModelsMock,
  },
}));

const baseRecording = {
  id: 'rec-1',
  title: 'Team Sync',
  started_at: 1_700_000_000,
  ended_at: 1_700_000_600,
  duration_seconds: 600,
  status: 'ready',
  tier1_transcript: 'Transcript from the meeting',
  tier2_transcript_json: null,
  ai_summary: null,
  ai_actions_json: null,
  ai_title_generated: false,
};

describe('MeetingRecordingDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsHandler = null;
    getEnabledModelsMock.mockResolvedValue(['openai/gpt-4o-mini', 'anthropic/claude-3-7-sonnet']);
    wsSubscribeMock.mockImplementation((handler: (msg: WsMessage) => void) => {
      wsHandler = handler;
      return vi.fn();
    });
  });

  test('sends initial load request and renders loaded recording', async () => {
    render(<MeetingRecordingDetail />);

    await waitFor(() => {
      expect(wsSendMock).toHaveBeenCalledWith({ type: 'load_meeting_recording', recording_id: 'rec-1' });
    });

    expect(getEnabledModelsMock).toHaveBeenCalled();
    expect(wsHandler).not.toBeNull();

    await dispatchWsMessage({ type: 'meeting_recording_loaded', content: baseRecording });

    expect(await screen.findByText('Team Sync')).toBeInTheDocument();
    expect(screen.getByText('Transcript')).toBeInTheDocument();
  });

  test('sends summarize request with selected model', async () => {
    render(<MeetingRecordingDetail />);

    await dispatchWsMessage({ type: 'meeting_recording_loaded', content: baseRecording });

    const modelSelect = await screen.findByRole('combobox');
    fireEvent.change(modelSelect, { target: { value: 'anthropic/claude-3-7-sonnet' } });

    fireEvent.click(screen.getByRole('button', { name: 'Summarize Recording' }));

    expect(wsSendMock).toHaveBeenCalledWith({
      type: 'meeting_generate_analysis',
      recording_id: 'rec-1',
      model: 'anthropic/claude-3-7-sonnet',
    });
  });

  test('handles analysis started and complete websocket events', async () => {
    render(<MeetingRecordingDetail />);
    wsHandler?.({ type: 'meeting_recording_loaded', content: baseRecording });

    fireEvent.click(await screen.findByRole('button', { name: 'Summarize Recording' }));

    expect(screen.getByText('Analyzing transcript...')).toBeInTheDocument();

    await dispatchWsMessage({
      type: 'meeting_analysis_complete',
      content: {
        recording_id: 'rec-1',
        summary: 'Clear summary output',
        actions: [
          {
            type: 'email',
            to: 'team@example.com',
            subject: 'Follow-up',
            body: 'Draft follow-up email',
          },
        ],
      },
    });

    expect(await screen.findByText('Clear summary output')).toBeInTheDocument();
    expect(screen.getByText('Suggested Actions')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create Draft' })).toBeInTheDocument();
  });

  test('handles analysis error and allows retry', async () => {
    render(<MeetingRecordingDetail />);
    await dispatchWsMessage({ type: 'meeting_recording_loaded', content: baseRecording });

    fireEvent.click(await screen.findByRole('button', { name: 'Summarize Recording' }));

    await dispatchWsMessage({
      type: 'meeting_analysis_error',
      content: {
        recording_id: 'rec-1',
        error: 'model timeout',
      },
    });

    expect(await screen.findByText(/Analysis failed: model timeout/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(wsSendMock).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'meeting_generate_analysis',
        recording_id: 'rec-1',
      }),
    );
  });

  test('sends action execute payload and shows action result status', async () => {
    render(<MeetingRecordingDetail />);

    await dispatchWsMessage({
      type: 'meeting_recording_loaded',
      content: {
        ...baseRecording,
        ai_summary: 'Summary exists',
        ai_actions_json: JSON.stringify([
          {
            type: 'calendar_event',
            title: 'Schedule follow-up',
            date: '2026-03-22',
            time: '09:00',
            duration_minutes: 30,
            description: 'Plan next sprint',
          },
        ]),
      },
    });

    const executeButton = await screen.findByRole('button', { name: 'Create Event' });
    fireEvent.click(executeButton);

    expect(wsSendMock).toHaveBeenCalledWith({
      type: 'meeting_execute_action',
      recording_id: 'rec-1',
      action_index: 0,
      action: {
        type: 'calendar_event',
        title: 'Schedule follow-up',
        date: '2026-03-22',
        time: '09:00',
        duration_minutes: 30,
        description: 'Plan next sprint',
      },
    });

    await dispatchWsMessage({
      type: 'meeting_action_result',
      content: {
        recording_id: 'rec-1',
        action_index: 0,
        success: true,
        result: 'created',
      },
    });

    expect(await screen.findByText('Done')).toBeInTheDocument();
  });
});
