import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import Settings from '../../pages/Settings';

vi.mock('../../components/TitleBar', () => ({
  default: () => <div data-testid="title-bar">title</div>,
}));

vi.mock('../../components/settings/SettingsModels', () => ({
  default: () => <div data-testid="settings-models">models</div>,
}));

vi.mock('../../components/settings/SettingsTools', () => ({
  default: () => <div data-testid="settings-tools">tools</div>,
}));

vi.mock('../../components/settings/SettingsApiKey', () => ({
  default: ({ provider }: { provider: string }) => <div data-testid={`settings-key-${provider}`}>{provider}</div>,
}));

vi.mock('../../components/settings/SettingsConnections', () => ({
  default: () => <div data-testid="settings-connections">connections</div>,
}));

vi.mock('../../components/settings/SettingsSystemPrompt', () => ({
  default: () => <div data-testid="settings-prompt">prompt</div>,
}));

vi.mock('../../components/settings/SettingsSkills', () => ({
  default: () => <div data-testid="settings-skills">skills</div>,
}));

vi.mock('../../components/settings/SettingsMemory', () => ({
  default: () => <div data-testid="settings-memory">memory</div>,
}));

vi.mock('../../components/settings/MeetingRecorderSettings', () => ({
  default: () => <div data-testid="settings-meeting">meeting</div>,
}));

vi.mock('../../components/settings/SettingsSubAgents', () => ({
  default: () => <div data-testid="settings-subagents">subagents</div>,
}));

vi.mock('react-router-dom', () => ({
  useOutletContext: () => ({
    setMini: vi.fn(),
  }),
}));

describe('Settings page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test('renders default models tab content', () => {
    render(<Settings />);
    expect(screen.getByTestId('title-bar')).toBeInTheDocument();
    expect(screen.getByTestId('settings-models')).toBeInTheDocument();
  });

  test('switches tabs and renders associated sections', () => {
    render(<Settings />);

    fireEvent.click(screen.getByText('Connections'));
    expect(screen.getByTestId('settings-connections')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Tools'));
    expect(screen.getByTestId('settings-tools')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Skills'));
    expect(screen.getByTestId('settings-skills')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Memory'));
    expect(screen.getByTestId('settings-memory')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Meeting'));
    expect(screen.getByTestId('settings-meeting')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Sub-Agents'));
    expect(screen.getByTestId('settings-subagents')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Prompt'));
    expect(screen.getByTestId('settings-prompt')).toBeInTheDocument();
  });

  test('renders Ollama guidance and API key tabs', () => {
    render(<Settings />);

    fireEvent.click(screen.getByText('Ollama'));
    expect(screen.getByRole('heading', { name: 'Ollama' })).toBeInTheDocument();

    fireEvent.click(screen.getByText('Anthropic'));
    expect(screen.getByTestId('settings-key-anthropic')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Gemini'));
    expect(screen.getByTestId('settings-key-gemini')).toBeInTheDocument();

    fireEvent.click(screen.getByText('OpenAI'));
    expect(screen.getByTestId('settings-key-openai')).toBeInTheDocument();

    fireEvent.click(screen.getByText('OpenRouter'));
    expect(screen.getByTestId('settings-key-openrouter')).toBeInTheDocument();
  });
});

