import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import SettingsArtifacts from '../../../components/settings/SettingsArtifacts';
import { api } from '../../../services/api';
import type { ArtifactBlockData } from '../../../types';

const createTabMock = vi.fn();
const navigateMock = vi.fn();

vi.mock('../../../services/api', () => ({
  api: {
    listArtifacts: vi.fn(),
  },
}));

vi.mock('../../../components/ArtifactModal', () => ({
  ArtifactModal: ({
    artifact,
    onClose,
    onDeleted,
    onOpenConversation,
    onUpdated,
  }: {
    artifact: ArtifactBlockData;
    onClose: () => void;
    onDeleted?: () => void;
    onOpenConversation?: (conversationId: string) => void;
    onUpdated?: (artifact: ArtifactBlockData) => void;
  }) => (
    <div data-testid="artifact-modal">
      <div>{artifact.title}</div>
      <button
        type="button"
        onClick={() => onUpdated?.({
          ...artifact,
          title: 'updated-spec.md',
          content: '# Updated',
          sizeBytes: 64,
          lineCount: 4,
        })}
      >
        Trigger Update
      </button>
      <button
        type="button"
        onClick={() => onOpenConversation?.(artifact.conversationId ?? 'conversation-1')}
      >
        Open Conversation
      </button>
      <button type="button" onClick={() => onDeleted?.()}>
        Trigger Delete
      </button>
      <button type="button" onClick={onClose}>
        Close Modal
      </button>
    </div>
  ),
}));

vi.mock('../../../components/icons/AppIcons', () => ({
  RotateCcwIcon: ({ className }: { className?: string }) => <span data-testid="refresh-icon" className={className} />,
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => navigateMock,
}));

vi.mock('../../../contexts/TabContext', () => ({
  useTabs: () => ({
    createTab: createTabMock,
  }),
}));

const mockedApi = vi.mocked(api);

describe('SettingsArtifacts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.listArtifacts.mockResolvedValue({
      artifacts: [
        {
          id: 'artifact-1',
          type: 'markdown',
          title: 'spec.md',
          language: 'markdown',
          sizeBytes: 32,
          lineCount: 3,
          status: 'ready',
          content: '# Spec',
          conversationId: 'conversation-7',
          messageId: 'message-1',
          createdAt: 1_700_000_000_000,
          updatedAt: 1_700_000_050_000,
        },
      ],
      total: 1,
      page: 1,
      pageSize: 24,
    });
    createTabMock.mockReturnValue('tab-42');
  });

  test('loads artifacts, debounces search, filters by type, and refreshes the current page', async () => {
    render(<SettingsArtifacts />);

    expect(await screen.findByText('spec.md')).toBeInTheDocument();
    expect(mockedApi.listArtifacts).toHaveBeenCalledWith({
      query: '',
      type: undefined,
      page: 1,
      pageSize: 24,
    });

    fireEvent.change(screen.getByPlaceholderText('Search artifacts...'), {
      target: { value: 'spec' },
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 230));
    });

    await waitFor(() => {
      expect(mockedApi.listArtifacts).toHaveBeenLastCalledWith({
        query: 'spec',
        type: undefined,
        page: 1,
        pageSize: 24,
      });
    });

    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: 'markdown' },
    });

    await waitFor(() => {
      expect(mockedApi.listArtifacts).toHaveBeenLastCalledWith({
        query: 'spec',
        type: 'markdown',
        page: 1,
        pageSize: 24,
      });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Refresh artifacts' }));

    await waitFor(() => {
      expect(mockedApi.listArtifacts).toHaveBeenLastCalledWith({
        query: 'spec',
        type: 'markdown',
        page: 1,
        pageSize: 24,
      });
    });
  });

  test('opens the artifact modal, applies updates, refreshes after delete, and navigates to the linked conversation', async () => {
    mockedApi.listArtifacts
      .mockResolvedValueOnce({
        artifacts: [
          {
            id: 'artifact-1',
            type: 'markdown',
            title: 'spec.md',
            language: 'markdown',
            sizeBytes: 32,
            lineCount: 3,
            status: 'ready',
            content: '# Spec',
            conversationId: 'conversation-7',
            messageId: 'message-1',
            createdAt: 1_700_000_000_000,
            updatedAt: 1_700_000_050_000,
          },
        ],
        total: 1,
        page: 1,
        pageSize: 24,
      })
      .mockResolvedValueOnce({
        artifacts: [],
        total: 0,
        page: 1,
        pageSize: 24,
      });

    render(<SettingsArtifacts />);

    fireEvent.click(await screen.findByRole('button', { name: /spec\.md/i }));
    expect(screen.getByTestId('artifact-modal')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Trigger Update' }));
    expect(await screen.findByRole('button', { name: /updated-spec\.md/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Open Conversation' }));
    expect(createTabMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/', {
      state: { conversationId: 'conversation-7', tabId: 'tab-42' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Trigger Delete' }));

    await waitFor(() => {
      expect(mockedApi.listArtifacts).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText('No artifacts found for the current filters.')).toBeInTheDocument();
  });

  test('renders backend load errors and empty-state fallbacks', async () => {
    mockedApi.listArtifacts.mockRejectedValueOnce(new Error('Artifact index offline'));

    render(<SettingsArtifacts />);

    expect(await screen.findByText('Artifact index offline')).toBeInTheDocument();
    expect(screen.getByText('No artifacts found for the current filters.')).toBeInTheDocument();
  });
});
