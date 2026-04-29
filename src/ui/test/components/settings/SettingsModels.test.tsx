import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SettingsModels from '../../../components/settings/SettingsModels'

// Mock the WebSocket context
const sendMock = vi.fn();
const subscribeMock = vi.fn();
const unsubscribeMock = vi.fn();

vi.mock('../../../contexts/WebSocketContext', () => ({
  useWebSocket: () => ({
    send: sendMock,
    subscribe: subscribeMock,
  }),
}));

// Mock the api module
vi.mock('../../../services/api', () => ({
  api: {
    getOllamaModels: vi.fn(),
    getOllamaModelInfo: vi.fn(),
    getEnabledModels: vi.fn(),
    setEnabledModels: vi.fn(),
    getApiKeyStatus: vi.fn(),
    getOpenAICodexStatus: vi.fn(),
    getProviderModels: vi.fn(),
  },
}))

// Mock the modelDisplay utils
vi.mock('../../../utils/modelDisplay', () => ({
  formatModelLabel: vi.fn((id: string) => id.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())),
  getProviderLabel: vi.fn((provider: string) => {
    const labels: Record<string, string> = {
      anthropic: 'Anthropic',
      openai: 'OpenAI',
      'openai-codex': 'ChatGPT Subscription',
      gemini: 'Gemini',
      openrouter: 'OpenRouter',
      ollama: 'Ollama',
    }
    return labels[provider] || provider
  }),
}))

// Get the mocked api
import { api } from '../../../services/api'
const mockedApi = vi.mocked(api)

// Sample test data
const mockOllamaModels = [
  { name: 'llama3.2:latest', size: 4294967296, parameter_size: '8B', quantization: 'Q4_0' },
  { name: 'qwen2.5:14b', size: 8589934592, parameter_size: '14B', quantization: 'Q5_K_M' },
]

const mockAnthropicModels = [
  { id: 'claude-sonnet-4-20250514', provider: 'anthropic', display_name: 'Claude Sonnet 4' },
  { id: 'claude-3-5-sonnet-20241022', provider: 'anthropic', display_name: 'Claude 3.5 Sonnet' },
]

const mockOpenAIModels = [
  { id: 'gpt-4o', provider: 'openai', display_name: 'GPT-4o' },
  { id: 'gpt-4o-mini', provider: 'openai', display_name: 'GPT-4o Mini' },
]

const mockOpenAICodexModels = [
  { id: 'openai-codex/gpt-5.4', provider: 'openai-codex', display_name: 'GPT-5.4' },
]

const mockGeminiModels = [
  { id: 'gemini-2.0-flash', provider: 'gemini', display_name: 'Gemini 2.0 Flash' },
]

const mockOpenRouterModels = [
  { id: 'anthropic/claude-3.5-sonnet', provider: 'openrouter', display_name: 'Claude 3.5 Sonnet', provider_group: 'anthropic', context_length: 200000 },
  { id: 'openai/gpt-4o', provider: 'openrouter', display_name: 'GPT-4o', provider_group: 'openai', context_length: 128000 },
]

const mockKeyStatusWithKeys = {
  anthropic: { has_key: true, masked: 'sk-ant-...xyz' },
  openai: { has_key: true, masked: 'sk-...abc' },
  gemini: { has_key: true, masked: 'AIza...def' },
  openrouter: { has_key: true, masked: 'sk-or-...ghi' },
}

const mockKeyStatusNoKeys = {
  anthropic: { has_key: false, masked: null },
  openai: { has_key: false, masked: null },
  gemini: { has_key: false, masked: null },
  openrouter: { has_key: false, masked: null },
}

const mockCodexDisconnected = {
  available: true,
  connected: false,
  account_type: null,
  email: null,
  plan_type: null,
  requires_openai_auth: true,
  auth_in_progress: false,
  login_method: null,
  login_id: null,
  auth_url: null,
  verification_url: null,
  user_code: null,
  auth_mode: null,
  last_error: null,
  binary_path: 'codex.exe',
}

describe('SettingsModels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Set up subscribe mock to return unsubscribe function
    subscribeMock.mockImplementation(() => unsubscribeMock)
    mockedApi.getOllamaModelInfo.mockResolvedValue({
      success: true,
      data: {
        name: 'llama3.2',
        tag: 'latest',
        full_name: 'llama3.2:latest',
        family: 'llama',
        families: ['llama'],
        parameter_size: '8B',
        quantization: 'Q4_0',
        format: 'gguf',
        architecture: 'amd64',
        os: 'linux',
        total_size_bytes: 4294967296,
        total_size_human: '4.00 GB',
        config_size_bytes: 512,
        layers: [],
        manifest_url: 'https://registry.ollama.ai/v2/library/llama3.2/manifests/latest',
        config_url: 'https://registry.ollama.ai/v2/library/llama3.2/blobs/sha256:abc',
        is_installed: false,
      },
    })
    mockedApi.getOpenAICodexStatus.mockResolvedValue(mockCodexDisconnected)
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  describe('Loading State', () => {
    test('should display loading message while fetching data', async () => {
      // Create promises that won't resolve immediately
      mockedApi.getEnabledModels.mockImplementation(() => new Promise(() => {}))
      mockedApi.getApiKeyStatus.mockImplementation(() => new Promise(() => {}))
      mockedApi.getOllamaModels.mockImplementation(() => new Promise(() => {}))

      render(<SettingsModels />)

      expect(screen.getByText('Loading models...')).toBeInTheDocument()
    })

    test('should hide loading message after data is fetched', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.queryByText('Loading models...')).not.toBeInTheDocument()
      })
    })
  })

  describe('Ollama Models Section', () => {
    test('should render Ollama section header', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('Ollama')).toBeInTheDocument()
      })
    })

    test('should render Ollama models list', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('llama3.2:latest')).toBeInTheDocument()
        expect(screen.getByText('qwen2.5:14b')).toBeInTheDocument()
      })
    })

    test('should display model metadata (size, parameters, quantization)', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText(/8B/)).toBeInTheDocument()
        expect(screen.getByText(/Q4_0/)).toBeInTheDocument()
        expect(screen.getByText(/14B/)).toBeInTheDocument()
        expect(screen.getByText(/Q5_K_M/)).toBeInTheDocument()
      })
    })

    test('should show empty message when no Ollama models found', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText(/No Ollama models found/)).toBeInTheDocument()
        expect(screen.getByText(/ollama pull model-name/)).toBeInTheDocument()
      })
    })

    test('should show Ollama error when provided', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [], error: 'Ollama is not running' })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('Ollama is not running')).toBeInTheDocument()
      })
    })

    test('should display enabled state for Ollama models', async () => {
      mockedApi.getEnabledModels.mockResolvedValue(['llama3.2:latest'])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })

      render(<SettingsModels />)

      await waitFor(() => {
        const llamaModel = screen.getByText('llama3.2:latest').closest('.settings-models-ollama-model')
        expect(llamaModel).toHaveClass('settings-models-enabled')
      })
    })
  })

  describe('Toggle Model Enable/Disable', () => {
    test('should toggle Ollama model on click', async () => {
      const user = userEvent.setup()
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })
      mockedApi.setEnabledModels.mockResolvedValue(undefined)

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('llama3.2:latest')).toBeInTheDocument()
      })

      const llamaModel = screen.getByText('llama3.2:latest').closest('.settings-models-ollama-model')
      await user.click(llamaModel!)

      expect(mockedApi.setEnabledModels).toHaveBeenCalledWith(['llama3.2:latest'])
    })

    test('should disable model when clicking on enabled model', async () => {
      const user = userEvent.setup()
      mockedApi.getEnabledModels.mockResolvedValue(['llama3.2:latest'])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })
      mockedApi.setEnabledModels.mockResolvedValue(undefined)

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('llama3.2:latest')).toBeInTheDocument()
      })

      const llamaModel = screen.getByText('llama3.2:latest').closest('.settings-models-ollama-model')
      await user.click(llamaModel!)

      expect(mockedApi.setEnabledModels).toHaveBeenCalledWith([])
    })

    test('should toggle cloud model on click', async () => {
      const user = userEvent.setup()
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusWithKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'anthropic') return mockAnthropicModels
        return []
      })
      mockedApi.setEnabledModels.mockResolvedValue(undefined)

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('Claude Sonnet 4 20250514')).toBeInTheDocument()
      })

      const claudeModel = screen.getByText('Claude Sonnet 4 20250514').closest('.settings-models-anthropic-model')
      await user.click(claudeModel!)

      expect(mockedApi.setEnabledModels).toHaveBeenCalledWith(['claude-sonnet-4-20250514'])
    })
  })

  describe('Cloud Provider Models', () => {
    test('should render Anthropic section when API key is set', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusWithKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'anthropic') return mockAnthropicModels
        return []
      })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('Anthropic')).toBeInTheDocument()
        expect(screen.getByText('Claude Sonnet 4 20250514')).toBeInTheDocument()
      })
    })

    test('should show "No API key configured" message when key is not set', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })

      render(<SettingsModels />)

      await waitFor(() => {
        const noKeyMessages = screen.getAllByText(/No API key configured/)
        expect(noKeyMessages.length).toBeGreaterThan(0)
      })
    })

    test('should render OpenAI section when API key is set', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusWithKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'openai') return mockOpenAIModels
        return []
      })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('OpenAI')).toBeInTheDocument()
        expect(screen.getByText('Gpt 4o')).toBeInTheDocument()
      })
    })

    test('should render ChatGPT subscription models when connected', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOpenAICodexStatus.mockResolvedValue({
        ...mockCodexDisconnected,
        connected: true,
        email: 'user@example.com',
        plan_type: 'plus',
      })
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'openai-codex') return mockOpenAICodexModels
        return []
      })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('ChatGPT Subscription')).toBeInTheDocument()
        expect(screen.getByText('GPT-5.4')).toBeInTheDocument()
      })
    })

    test('should show ChatGPT connect placeholder when subscription is disconnected', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText(/Connect ChatGPT in the OpenAI tab/)).toBeInTheDocument()
      })
    })

    test('should render Gemini section when API key is set', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusWithKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'gemini') return mockGeminiModels
        return []
      })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('Gemini')).toBeInTheDocument()
        expect(screen.getByText('Gemini 2.0 Flash')).toBeInTheDocument()
      })
    })

    test('should render OpenRouter section with grouped models', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusWithKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'openrouter') return mockOpenRouterModels
        return []
      })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('OpenRouter')).toBeInTheDocument()
      })
    })

    test('should show provider error when API call fails', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusWithKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })
      mockedApi.getProviderModels.mockImplementation(async (provider) => {
        if (provider === 'anthropic') throw new Error('Invalid API key')
        return []
      })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('Invalid API key')).toBeInTheDocument()
      })
    })
  })

  describe('Refresh Functionality', () => {
    test('should have refresh buttons for each provider section', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })

      render(<SettingsModels />)

      await waitFor(() => {
        const refreshButtons = screen.getAllByRole('button', { name: /refresh/i })
        expect(refreshButtons.length).toBeGreaterThanOrEqual(1)
      })
    })

    test('should refresh Ollama models when clicking refresh button', async () => {
      const user = userEvent.setup()
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: mockOllamaModels })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('llama3.2:latest')).toBeInTheDocument()
      })

      const refreshButtons = screen.getAllByRole('button', { name: /refresh/i })
      await user.click(refreshButtons[0])

      // Should be called initially (false) and then on refresh (true)
      await waitFor(() => {
        expect(mockedApi.getOllamaModels).toHaveBeenCalledWith(true)
      })
    })

    test('should show "Refreshing..." text while refreshing', async () => {
      const user = userEvent.setup()
      let resolveRefresh: () => void
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels
        .mockResolvedValueOnce({ models: mockOllamaModels })
        .mockImplementationOnce(() => new Promise((resolve) => {
          resolveRefresh = () => resolve({ models: mockOllamaModels })
        }))

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText('llama3.2:latest')).toBeInTheDocument()
      })

      const refreshButtons = screen.getAllByRole('button', { name: /refresh/i })
      await user.click(refreshButtons[0])

      expect(refreshButtons[0]).toHaveAttribute('title', 'Refreshing...')

      // Resolve the refresh
      resolveRefresh!()
      await waitFor(() => {
        expect(refreshButtons[0]).toHaveAttribute('title', 'Refresh')
      })
    })
  })

  describe('Error Handling', () => {
    test('should show backend error when initial fetch fails', async () => {
      mockedApi.getEnabledModels.mockRejectedValue(new Error('Network error'))
      mockedApi.getApiKeyStatus.mockRejectedValue(new Error('Network error'))

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByText(/Could not reach the backend/)).toBeInTheDocument()
      })
    })
  })

  describe('Header', () => {
    test('should render page header with title and description', async () => {
      mockedApi.getEnabledModels.mockResolvedValue([])
      mockedApi.getApiKeyStatus.mockResolvedValue(mockKeyStatusNoKeys)
      mockedApi.getOllamaModels.mockResolvedValue({ models: [] })

      render(<SettingsModels />)

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Models' })).toBeInTheDocument()
        expect(screen.getByText('Enable or disable models for your workspace.')).toBeInTheDocument()
      })
    })
  })
})
