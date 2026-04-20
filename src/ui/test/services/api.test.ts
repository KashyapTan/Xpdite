import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createApiService, api } from '../../services/api';

// Mock the portDiscovery module
vi.mock('../../services/portDiscovery', () => ({
  discoverServerPort: vi.fn().mockResolvedValue(8000),
  getHttpBaseUrl: vi.fn().mockReturnValue('http://localhost:8000'),
  getWsBaseUrl: vi.fn().mockReturnValue('ws://localhost:8000'),
}));

// Store original fetch
const originalFetch = global.fetch;

describe('createApiService', () => {
  let mockSend: ReturnType<typeof vi.fn>;
  let mockGetTabId: ReturnType<typeof vi.fn>;
  let apiService: ReturnType<typeof createApiService>;

  beforeEach(() => {
    mockSend = vi.fn();
    mockGetTabId = vi.fn().mockReturnValue('test-tab-123');
    apiService = createApiService(mockSend, mockGetTabId);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('factory function', () => {
    test('returns object with all required WebSocket methods', () => {
      expect(apiService).toHaveProperty('submitQuery');
      expect(apiService).toHaveProperty('clearContext');
      expect(apiService).toHaveProperty('removeScreenshot');
      expect(apiService).toHaveProperty('setCaptureMode');
      expect(apiService).toHaveProperty('stopStreaming');
      expect(apiService).toHaveProperty('cancelQueuedItem');
      expect(apiService).toHaveProperty('getConversations');
      expect(apiService).toHaveProperty('searchConversations');
      expect(apiService).toHaveProperty('resumeConversation');
      expect(apiService).toHaveProperty('deleteConversation');
      expect(apiService).toHaveProperty('tabCreated');
      expect(apiService).toHaveProperty('tabClosed');
      expect(apiService).toHaveProperty('tabActivated');
      expect(apiService).toHaveProperty('startMeetingRecording');
      expect(apiService).toHaveProperty('stopMeetingRecording');
      expect(apiService).toHaveProperty('getMeetingRecordings');
      expect(apiService).toHaveProperty('searchMeetingRecordings');
      expect(apiService).toHaveProperty('deleteMeetingRecording');
      expect(apiService).toHaveProperty('getMeetingRecordingStatus');
    });

    test('uses default tab ID when getTabId is not provided', () => {
      const service = createApiService(mockSend);
      service.submitQuery('test', 'area');
      expect(mockSend).toHaveBeenCalledWith(
        expect.objectContaining({ tab_id: 'default' })
      );
    });
  });

  describe('submitQuery', () => {
    test('sends correct message format with tab_id', () => {
      apiService.submitQuery('test query', 'area');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'submit_query',
        content: 'test query',
        capture_mode: 'area',
        tab_id: 'test-tab-123',
      });
    });

    test('calls getTabId to inject current tab', () => {
      apiService.submitQuery('test', 'fullscreen');
      expect(mockGetTabId).toHaveBeenCalled();
    });
  });

  describe('clearContext', () => {
    test('sends clear_context message with tab_id', () => {
      apiService.clearContext();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'clear_context',
        tab_id: 'test-tab-123',
      });
    });
  });

  describe('removeScreenshot', () => {
    test('sends remove_screenshot message with id and tab_id', () => {
      apiService.removeScreenshot('screenshot-456');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'remove_screenshot',
        id: 'screenshot-456',
        tab_id: 'test-tab-123',
      });
    });
  });

  describe('setCaptureMode', () => {
    test('sends set_capture_mode message with mode and tab_id', () => {
      apiService.setCaptureMode('fullscreen');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'set_capture_mode',
        mode: 'fullscreen',
        tab_id: 'test-tab-123',
      });
    });
  });

  describe('stopStreaming', () => {
    test('sends stop_streaming message with tab_id', () => {
      apiService.stopStreaming();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'stop_streaming',
        tab_id: 'test-tab-123',
      });
    });
  });

  describe('cancelQueuedItem', () => {
    test('sends cancel_queued_item message with item_id and tab_id', () => {
      apiService.cancelQueuedItem('item-789');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'cancel_queued_item',
        item_id: 'item-789',
        tab_id: 'test-tab-123',
      });
    });
  });

  describe('getConversations', () => {
    test('sends get_conversations message without tab_id', () => {
      apiService.getConversations();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'get_conversations',
        limit: 50,
        offset: 0,
      });
    });

    test('respects custom limit and offset', () => {
      apiService.getConversations(10, 20);
      expect(mockSend).toHaveBeenCalledWith({
        type: 'get_conversations',
        limit: 10,
        offset: 20,
      });
    });
  });

  describe('searchConversations', () => {
    test('sends search_conversations message with query', () => {
      apiService.searchConversations('test search');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'search_conversations',
        query: 'test search',
      });
    });
  });

  describe('resumeConversation', () => {
    test('sends resume_conversation message with conversation_id and tab_id', () => {
      apiService.resumeConversation('conv-123');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'resume_conversation',
        conversation_id: 'conv-123',
        tab_id: 'test-tab-123',
      });
    });
  });

  describe('deleteConversation', () => {
    test('sends delete_conversation message with conversation_id (no tab_id)', () => {
      apiService.deleteConversation('conv-456');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'delete_conversation',
        conversation_id: 'conv-456',
      });
    });
  });

  describe('tab lifecycle methods', () => {
    test('tabCreated sends correct message without auto tab_id', () => {
      apiService.tabCreated('new-tab-id');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'tab_created',
        tab_id: 'new-tab-id',
      });
    });

    test('tabClosed sends correct message without auto tab_id', () => {
      apiService.tabClosed('closed-tab-id');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'tab_closed',
        tab_id: 'closed-tab-id',
      });
    });

    test('tabActivated sends correct message without auto tab_id', () => {
      apiService.tabActivated('active-tab-id');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'tab_activated',
        tab_id: 'active-tab-id',
      });
    });
  });

  describe('meeting recording methods', () => {
    test('startMeetingRecording sends correct message', () => {
      apiService.startMeetingRecording();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'meeting_start_recording',
      });
    });

    test('stopMeetingRecording sends correct message', () => {
      apiService.stopMeetingRecording();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'meeting_stop_recording',
      });
    });

    test('getMeetingRecordings sends correct message with defaults', () => {
      apiService.getMeetingRecordings();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'get_meeting_recordings',
        limit: 50,
        offset: 0,
      });
    });

    test('getMeetingRecordings respects custom pagination', () => {
      apiService.getMeetingRecordings(25, 10);
      expect(mockSend).toHaveBeenCalledWith({
        type: 'get_meeting_recordings',
        limit: 25,
        offset: 10,
      });
    });

    test('searchMeetingRecordings sends correct message', () => {
      apiService.searchMeetingRecordings('meeting search');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'search_meeting_recordings',
        query: 'meeting search',
      });
    });

    test('deleteMeetingRecording sends correct message', () => {
      apiService.deleteMeetingRecording('recording-123');
      expect(mockSend).toHaveBeenCalledWith({
        type: 'delete_meeting_recording',
        recording_id: 'recording-123',
      });
    });

    test('getMeetingRecordingStatus sends correct message', () => {
      apiService.getMeetingRecordingStatus();
      expect(mockSend).toHaveBeenCalledWith({
        type: 'meeting_get_status',
      });
    });
  });
});

describe('api singleton - HTTP endpoints', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe('HTTP_BASE_URL and WS_BASE_URL getters', () => {
    test('HTTP_BASE_URL returns correct URL', () => {
      expect(api.HTTP_BASE_URL).toBe('http://localhost:8000');
    });

    test('WS_BASE_URL returns correct URL', () => {
      expect(api.WS_BASE_URL).toBe('ws://localhost:8000');
    });
  });

  describe('getOllamaModels', () => {
    test('returns models on success with array response', async () => {
      const mockModels = [
        { name: 'llama3', size: 1000000, parameter_size: '7B', quantization: 'Q4' },
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockModels),
      });

      const result = await api.getOllamaModels();
      expect(result).toEqual({ models: mockModels });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/models/ollama');
    });

    test('returns models from nested response format', async () => {
      const mockModels = [
        { name: 'qwen', size: 2000000, parameter_size: '8B', quantization: 'Q5' },
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ models: mockModels, error: undefined }),
      });

      const result = await api.getOllamaModels();
      expect(result).toEqual({ models: mockModels, error: undefined });
    });

    test('passes refresh parameter when true', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      });

      await api.getOllamaModels(true);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/models/ollama?refresh=true');
    });

    test('returns error from backend when present', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ models: [], error: 'Ollama not running' }),
      });

      const result = await api.getOllamaModels();
      expect(result).toEqual({ models: [], error: 'Ollama not running' });
    });

    test('returns empty models on fetch error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getOllamaModels();
      expect(result).toEqual({ models: [] });
    });

    test('returns empty models on non-ok response', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      });

      const result = await api.getOllamaModels();
      expect(result).toEqual({ models: [] });
    });
  });

  describe('getEnabledModels', () => {
    test('returns enabled models on success', async () => {
      const mockModels = ['model1', 'model2'];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockModels),
      });

      const result = await api.getEnabledModels();
      expect(result).toEqual(mockModels);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/models/enabled');
    });

    test('returns empty array on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getEnabledModels();
      expect(result).toEqual([]);
    });

    test('returns empty array on non-ok response', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false });

      const result = await api.getEnabledModels();
      expect(result).toEqual([]);
    });
  });

  describe('setEnabledModels', () => {
    test('sends PUT request with correct body', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.setEnabledModels(['model1', 'model2']);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/models/enabled', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ models: ['model1', 'model2'] }),
      });
    });

    test('handles error gracefully without throwing', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      await expect(api.setEnabledModels(['model1'])).resolves.toBeUndefined();
      expect(consoleSpy).toHaveBeenCalledWith('Failed to save enabled models');
      consoleSpy.mockRestore();
    });
  });

  describe('healthCheck', () => {
    test('returns true when server is healthy', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      const result = await api.healthCheck();
      expect(result).toBe(true);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/health');
    });

    test('returns false when server is not healthy', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false });

      const result = await api.healthCheck();
      expect(result).toBe(false);
    });

    test('returns false on network error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.healthCheck();
      expect(result).toBe(false);
    });
  });

  describe('getApiKeyStatus', () => {
    test('returns key status on success', async () => {
      const mockStatus = {
        anthropic: { has_key: true, masked: 'sk-***abc' },
        openai: { has_key: false, masked: null },
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockStatus),
      });

      const result = await api.getApiKeyStatus();
      expect(result).toEqual(mockStatus);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/keys');
    });

    test('returns empty object on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getApiKeyStatus();
      expect(result).toEqual({});
    });
  });

  describe('saveApiKey', () => {
    test('saves key successfully', async () => {
      const mockResponse = { status: 'ok', provider: 'anthropic', masked: 'sk-***xyz' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      });

      const result = await api.saveApiKey('anthropic', 'sk-my-secret-key');
      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/keys/anthropic', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'sk-my-secret-key' }),
      });
    });

    test('throws error with detail message on failure', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({ detail: 'Invalid API key format' }),
      });

      await expect(api.saveApiKey('anthropic', 'bad-key')).rejects.toThrow(
        'Invalid API key format'
      );
    });

    test('throws default error when no detail provided', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({}),
      });

      await expect(api.saveApiKey('anthropic', 'bad-key')).rejects.toThrow(
        'Failed to save API key'
      );
    });

    test('throws default error when json parsing fails', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.reject(new Error('Parse error')),
      });

      await expect(api.saveApiKey('anthropic', 'bad-key')).rejects.toThrow(
        'Failed to save API key'
      );
    });
  });

  describe('deleteApiKey', () => {
    test('sends DELETE request for provider', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.deleteApiKey('openai');
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/keys/openai', {
        method: 'DELETE',
      });
    });

    test('handles error gracefully without throwing', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      await expect(api.deleteApiKey('openai')).resolves.toBeUndefined();
      expect(consoleSpy).toHaveBeenCalledWith('Failed to delete API key for openai');
      consoleSpy.mockRestore();
    });
  });

  describe('getProviderModels', () => {
    test('returns normalized models for anthropic', async () => {
      const rawModels = [
        { id: 'claude-3-opus', display_name: 'Claude 3 Opus', context_length: 200000 },
        { id: 'claude-3-sonnet', display_name: 'Claude 3 Sonnet' },
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(rawModels),
      });

      const result = await api.getProviderModels('anthropic');
      expect(result).toEqual([
        { id: 'claude-3-opus', provider: 'anthropic', display_name: 'Claude 3 Opus', context_length: 200000, provider_group: undefined },
        { id: 'claude-3-sonnet', provider: 'anthropic', display_name: 'Claude 3 Sonnet', context_length: undefined, provider_group: undefined },
      ]);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/models/anthropic');
    });

    test('handles models with name instead of id', async () => {
      const rawModels = [{ name: 'gpt-4', description: 'GPT-4' }];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(rawModels),
      });

      const result = await api.getProviderModels('openai');
      expect(result).toEqual([
        { id: 'gpt-4', provider: 'openai', display_name: 'GPT-4', context_length: undefined, provider_group: undefined },
      ]);
    });

    test('filters out models without id or name', async () => {
      const rawModels = [
        { id: 'valid-model' },
        { display_name: 'No ID Model' }, // Should be filtered
        { id: '', name: '' }, // Should be filtered
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(rawModels),
      });

      const result = await api.getProviderModels('gemini');
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('valid-model');
    });

    test('passes refresh parameter', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([]),
      });

      await api.getProviderModels('openrouter', true);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/models/openrouter?refresh=true');
    });

    test('throws error with detail on failure', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: 'API key not configured' }),
      });

      await expect(api.getProviderModels('anthropic')).rejects.toThrow(
        'API key not configured'
      );
    });

    test('throws error with message fallback', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ message: 'Server error' }),
      });

      await expect(api.getProviderModels('openai')).rejects.toThrow('Server error');
    });

    test('throws default error when no detail or message', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve({}),
      });

      await expect(api.getProviderModels('gemini')).rejects.toThrow(
        'Failed to fetch gemini models'
      );
    });

    test('returns empty array for non-array response', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ error: 'unexpected format' }),
      });

      const result = await api.getProviderModels('anthropic');
      expect(result).toEqual([]);
    });
  });

  describe('getGoogleStatus', () => {
    test('returns Google status on success', async () => {
      const mockStatus = { connected: true, email: 'test@example.com', auth_in_progress: false };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockStatus),
      });

      const result = await api.getGoogleStatus();
      expect(result).toEqual(mockStatus);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/google/status');
    });

    test('returns default status on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getGoogleStatus();
      expect(result).toEqual({ connected: false, email: null, auth_in_progress: false });
    });
  });

  describe('connectGoogle', () => {
    test('returns success response', async () => {
      const mockResponse = { success: true, email: 'test@example.com' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      });

      const result = await api.connectGoogle();
      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/google/connect', {
        method: 'POST',
      });
    });

    test('returns error response on failure with detail', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({ detail: 'Auth timeout' }),
      });

      const result = await api.connectGoogle();
      expect(result).toEqual({ success: false, error: 'Auth timeout' });
    });

    test('returns default error when json parse fails', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.reject(new Error('Parse error')),
      });

      const result = await api.connectGoogle();
      expect(result).toEqual({ success: false, error: 'Connection failed' });
    });
  });

  describe('disconnectGoogle', () => {
    test('returns response from server', async () => {
      const mockResponse = { success: true };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      });

      const result = await api.disconnectGoogle();
      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/google/disconnect', {
        method: 'POST',
      });
    });
  });

  describe('getMcpServers', () => {
    test('returns MCP servers on success', async () => {
      const mockServers = [
        {
          server: 'filesystem',
          display_name: 'filesystem',
          tools: [{ id: 'read', name: 'read' }, { id: 'write', name: 'write' }],
        },
        {
          server: 'gmail',
          display_name: 'gmail',
          tools: [{ id: 'search', name: 'search' }, { id: 'send', name: 'send' }],
        },
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockServers),
      });

      const result = await api.getMcpServers();
      expect(result).toEqual(mockServers);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/mcp/servers');
    });

    test('returns empty array on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getMcpServers();
      expect(result).toEqual([]);
    });

    test('normalizes legacy object payload into server summaries', async () => {
      const legacyPayload = {
        filesystem: ['read', 'write'],
        terminal: [{ id: 'run_command', name: 'run_command' }],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(legacyPayload),
      });

      const result = await api.getMcpServers();

      expect(result).toEqual([
        {
          server: 'filesystem',
          display_name: 'filesystem',
          tools: [
            { id: 'read', name: 'read' },
            { id: 'write', name: 'write' },
          ],
        },
        {
          server: 'terminal',
          display_name: 'terminal',
          tools: [{ id: 'run_command', name: 'run_command' }],
        },
      ]);
    });
  });

  describe('getToolsSettings', () => {
    test('returns tools settings on success', async () => {
      const mockSettings = { always_on: ['tool1', 'tool2'], top_k: 10 };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockSettings),
      });

      const result = await api.getToolsSettings();
      expect(result).toEqual(mockSettings);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/tools');
    });

    test('returns default settings on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getToolsSettings();
      expect(result).toEqual({ always_on: [], top_k: 5 });
    });
  });

  describe('setToolsSettings', () => {
    test('sends PUT request with correct body', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.setToolsSettings(['tool1', 'tool2'], 15);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/tools', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ always_on: ['tool1', 'tool2'], top_k: 15 }),
      });
    });

    test('handles error gracefully without throwing', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      await expect(api.setToolsSettings([], 5)).resolves.toBeUndefined();
      expect(consoleSpy).toHaveBeenCalledWith('Failed to save tool settings');
      consoleSpy.mockRestore();
    });
  });

  describe('getSubAgentSettings', () => {
    test('returns sub-agent settings on success', async () => {
      const mockSettings = { fast_model: 'llama3', smart_model: 'claude-3' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockSettings),
      });

      const result = await api.getSubAgentSettings();
      expect(result).toEqual(mockSettings);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/sub-agents');
    });

    test('returns default settings on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await api.getSubAgentSettings();
      expect(result).toEqual({ fast_model: '', smart_model: '' });
    });
  });

  describe('setSubAgentSettings', () => {
    test('sends PUT request with correct body', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.setSubAgentSettings({ fast_model: 'llama3', smart_model: 'claude-3' });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/sub-agents', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fast_model: 'llama3', smart_model: 'claude-3' }),
      });
    });
  });

  describe('memory endpoints', () => {
    test('gets memory settings', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ profile_auto_inject: true }),
      });

      const result = await api.getMemorySettings();
      expect(result).toEqual({ profile_auto_inject: true });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/memory');
    });

    test('getMemorySettings throws on backend failure', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({ detail: 'settings unavailable' }),
      });

      await expect(api.getMemorySettings()).rejects.toThrow('settings unavailable');
    });

    test('sets memory settings', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.setMemorySettings({ profile_auto_inject: false });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/memory', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_auto_inject: false }),
      });
    });

    test('lists memories with optional folder filter', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ memories: [{ path: 'semantic/prefs.md' }] }),
      });

      const result = await api.listMemories('semantic');
      expect(result).toEqual([{ path: 'semantic/prefs.md' }]);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/memory?folder=semantic');
    });

    test('gets a single memory detail', async () => {
      const detail = { path: 'procedural/fix.md', body: 'Body', raw_text: '---' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(detail),
      });

      const result = await api.getMemory('procedural/fix.md');
      expect(result).toEqual(detail);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/memory/file?path=procedural%2Ffix.md');
    });

    test('updates a memory file', async () => {
      const memory = {
        path: 'procedural/fix.md',
        title: 'Fix',
        category: 'procedural',
        importance: 0.9,
        tags: ['sqlite'],
        abstract: 'A fix.',
        body: 'Body',
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(memory),
      });

      const result = await api.updateMemory(memory);
      expect(result).toEqual(memory);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/memory/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(memory),
      });
    });

    test('deletes a memory file', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.deleteMemory('procedural/fix.md');
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/memory/file?path=procedural%2Ffix.md', {
        method: 'DELETE',
      });
    });

    test('clears all memories', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, deleted_count: 3 }),
      });

      const result = await api.clearAllMemories();
      expect(result).toEqual({ success: true, deleted_count: 3 });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/memory', {
        method: 'DELETE',
      });
    });
  });

  describe('getSystemPrompt', () => {
    test('returns system prompt on success', async () => {
      const mockPrompt = { template: 'You are a helpful assistant', is_custom: true };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockPrompt),
      });

      const result = await api.getSystemPrompt();
      expect(result).toEqual(mockPrompt);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/system-prompt');
    });

    test('throws error on failure', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false });

      await expect(api.getSystemPrompt()).rejects.toThrow('Failed to fetch system prompt');
    });
  });

  describe('setSystemPrompt', () => {
    test('sends PUT request with template', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.setSystemPrompt('Custom prompt template');
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/settings/system-prompt', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template: 'Custom prompt template' }),
      });
    });

    test('throws error on failure', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false });

      await expect(api.setSystemPrompt('test')).rejects.toThrow('Failed to save system prompt');
    });
  });

  describe('skillsApi', () => {
    describe('getAll', () => {
      test('returns all skills on success', async () => {
        const mockSkills = [
          { name: 'skill1', description: 'Skill 1', enabled: true },
          { name: 'skill2', description: 'Skill 2', enabled: false },
        ];
        global.fetch = vi.fn().mockResolvedValue({
          ok: true,
          json: () => Promise.resolve(mockSkills),
        });

        const result = await api.skillsApi.getAll();
        expect(result).toEqual(mockSkills);
        expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/skills');
      });

      test('throws error on failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false });

        await expect(api.skillsApi.getAll()).rejects.toThrow('Failed to fetch skills');
      });
    });

    describe('getContent', () => {
      test('returns skill content on success', async () => {
        global.fetch = vi.fn().mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({ content: 'Skill content here' }),
        });

        const result = await api.skillsApi.getContent('skill1');
        expect(result).toBe('Skill content here');
        expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/skills/skill1/content');
      });

      test('throws error on failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false });

        await expect(api.skillsApi.getContent('skill1')).rejects.toThrow(
          'Failed to fetch skill content'
        );
      });
    });

    describe('create', () => {
      test('sends POST request with skill data', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: true });

        await api.skillsApi.create({
          name: 'new-skill',
          description: 'New skill',
          content: 'Skill content',
          slash_command: '/newskill',
          trigger_servers: ['server1'],
        });

        expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/skills', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: 'new-skill',
            description: 'New skill',
            content: 'Skill content',
            slash_command: '/newskill',
            trigger_servers: ['server1'],
          }),
        });
      });

      test('throws error with detail on failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({
          ok: false,
          json: () => Promise.resolve({ detail: 'Skill already exists' }),
        });

        await expect(
          api.skillsApi.create({ name: 'skill', description: 'test', content: 'test' })
        ).rejects.toThrow('Skill already exists');
      });

      test('throws default error when detail is missing', async () => {
        global.fetch = vi.fn().mockResolvedValue({
          ok: false,
          json: () => Promise.resolve({}),
        });

        await expect(
          api.skillsApi.create({ name: 'skill', description: 'test', content: 'test' })
        ).rejects.toThrow('Failed to create skill');
      });
    });

    describe('update', () => {
      test('sends PUT request with update data', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: true });

        await api.skillsApi.update('skill1', {
          description: 'Updated description',
          content: 'Updated content',
        });

        expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/skills/skill1', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            description: 'Updated description',
            content: 'Updated content',
          }),
        });
      });

      test('throws error with detail on failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({
          ok: false,
          json: () => Promise.resolve({ detail: 'Skill not found' }),
        });

        await expect(api.skillsApi.update('skill1', {})).rejects.toThrow('Skill not found');
      });
    });

    describe('toggle', () => {
      test('sends PATCH request with enabled flag', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: true });

        await api.skillsApi.toggle('skill1', true);

        expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/skills/skill1/toggle', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: true }),
        });
      });

      test('throws error on failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false });

        await expect(api.skillsApi.toggle('skill1', false)).rejects.toThrow(
          'Failed to toggle skill'
        );
      });
    });

    describe('delete', () => {
      test('sends DELETE request', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: true });

        await api.skillsApi.delete('skill1');

        expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/skills/skill1', {
          method: 'DELETE',
        });
      });

      test('throws error on failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false });

        await expect(api.skillsApi.delete('skill1')).rejects.toThrow('Failed to delete skill');
      });
    });
  });

  describe('mobile channels API', () => {
    test('gets paired mobile devices', async () => {
      const payload = {
        devices: [
          {
            id: 1,
            platform: 'telegram',
            sender_id: '123',
            display_name: 'Alice',
            paired_at: 1700000000,
            last_active: 1700000100,
          },
        ],
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.getMobilePairedDevices();

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/internal/mobile/devices');
    });

    test('generates a pairing code', async () => {
      const payload = { code: 'PAIR-123', expires_in_seconds: 600 };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.generateMobilePairingCode();

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/internal/mobile/pair/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expires_in_seconds: 600 }),
      });
    });

    test('revokes a paired mobile device', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.revokeMobilePairedDevice(42);

      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/internal/mobile/devices/42', {
        method: 'DELETE',
      });
    });

    test('returns empty mobile channel config when backend responds non-ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: false });

      const result = await api.getMobileChannelsConfig();

      expect(result).toEqual({ platforms: {} });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/mobile-channels/config');
    });

    test('saves mobile platform config', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.setMobilePlatformConfig('telegram', {
        enabled: true,
        token: 'bot-token',
      });

      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/mobile-channels/config/telegram', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: true,
          token: 'bot-token',
        }),
      });
    });

    test('surfaces JSON detail errors when saving mobile platform config fails', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        text: () => Promise.resolve(JSON.stringify({ detail: 'Token is invalid' })),
      });

      await expect(
        api.setMobilePlatformConfig('telegram', { token: 'bad-token' }),
      ).rejects.toThrow('Token is invalid');
    });

    test('falls back to plain text errors when saving mobile platform config fails', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        text: () => Promise.resolve('Bridge unavailable'),
      });

      await expect(
        api.setMobilePlatformConfig('telegram', { token: 'bad-token' }),
      ).rejects.toThrow('Bridge unavailable');
    });
  });

  describe('notifications API', () => {
    test('gets notifications and unread count', async () => {
      const payload = {
        notifications: [
          {
            id: 'notif-1',
            type: 'info',
            title: 'Done',
            body: 'Task finished',
            payload: null,
            created_at: 1700000000,
          },
        ],
        unread_count: 1,
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.getNotifications();

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/notifications');
    });

    test('gets notification count', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ count: 3 }),
      });

      const result = await api.getNotificationCount();

      expect(result).toEqual({ count: 3 });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/notifications/count');
    });

    test('dismisses one notification', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.dismissNotification('notif-2');

      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/notifications/notif-2', {
        method: 'DELETE',
      });
    });

    test('dismisses all notifications', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ dismissed_count: 5 }),
      });

      const result = await api.dismissAllNotifications();

      expect(result).toEqual({ dismissed_count: 5 });
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/notifications', {
        method: 'DELETE',
      });
    });
  });

  describe('scheduled jobs API', () => {
    test('gets scheduled jobs', async () => {
      const payload = {
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
            created_at: 1700000000,
            last_run_at: null,
            next_run_at: 1700003600,
            run_count: 0,
            missed: false,
          },
        ],
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.getScheduledJobs();

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/scheduled-jobs');
    });

    test('gets a single scheduled job', async () => {
      const payload = {
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
        created_at: 1700000000,
        last_run_at: null,
        next_run_at: 1700003600,
        run_count: 0,
        missed: false,
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.getScheduledJob('job-1');

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/scheduled-jobs/job-1');
    });

    test('creates a scheduled job', async () => {
      const input = {
        name: 'Morning Brief',
        cron_expression: '0 9 * * *',
        instruction: 'Summarize the inbox',
        timezone: 'America/New_York',
      };
      const payload = {
        ...input,
        id: 'job-1',
        model: null,
        delivery_platform: null,
        delivery_sender_id: null,
        enabled: true,
        is_one_shot: false,
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.createScheduledJob(input);

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/scheduled-jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      });
    });

    test('updates a scheduled job', async () => {
      const updates = {
        delivery_platform: 'telegram',
        delivery_sender_id: '@alice',
      };
      const payload = {
        id: 'job-1',
        name: 'Morning Brief',
        cron_expression: '0 9 * * *',
        instruction: 'Summarize the inbox',
        timezone: 'America/New_York',
        model: null,
        enabled: true,
        is_one_shot: false,
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.updateScheduledJob('job-1', updates);

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/scheduled-jobs/job-1', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
    });

    test('deletes a scheduled job', async () => {
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      await api.deleteScheduledJob('job-1');

      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/scheduled-jobs/job-1', {
        method: 'DELETE',
      });
    });

    test('pauses, resumes, and runs a scheduled job immediately', async () => {
      global.fetch = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ id: 'job-1', name: 'Morning Brief', enabled: false }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ id: 'job-1', name: 'Morning Brief', enabled: true, next_run_at: 1700003600 }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({ success: true, conversation_id: 'conv-1', job_name: 'Morning Brief' }),
        });

      await expect(api.pauseScheduledJob('job-1')).resolves.toEqual({
        id: 'job-1',
        name: 'Morning Brief',
        enabled: false,
      });
      await expect(api.resumeScheduledJob('job-1')).resolves.toEqual({
        id: 'job-1',
        name: 'Morning Brief',
        enabled: true,
        next_run_at: 1700003600,
      });
      await expect(api.runScheduledJobNow('job-1')).resolves.toEqual({
        success: true,
        conversation_id: 'conv-1',
        job_name: 'Morning Brief',
      });

      expect(vi.mocked(fetch).mock.calls).toEqual([
        ['http://localhost:8000/api/scheduled-jobs/job-1/pause', { method: 'POST' }],
        ['http://localhost:8000/api/scheduled-jobs/job-1/resume', { method: 'POST' }],
        ['http://localhost:8000/api/scheduled-jobs/job-1/run-now', { method: 'POST' }],
      ]);
    });

    test('gets scheduled-job conversation lists', async () => {
      global.fetch = vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            conversations: [{ id: 'conv-1', job_id: 'job-1', job_name: 'Morning Brief', title: 'Summary', created_at: 1, updated_at: 2 }],
          }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({
            conversations: [{ id: 'conv-2', job_id: 'job-1', job_name: 'Morning Brief', title: 'Retry', created_at: 3, updated_at: 4 }],
            job: { id: 'job-1', name: 'Morning Brief' },
          }),
        });

      await expect(api.getScheduledJobConversations()).resolves.toEqual({
        conversations: [{ id: 'conv-1', job_id: 'job-1', job_name: 'Morning Brief', title: 'Summary', created_at: 1, updated_at: 2 }],
      });
      await expect(api.getJobConversations('job-1')).resolves.toEqual({
        conversations: [{ id: 'conv-2', job_id: 'job-1', job_name: 'Morning Brief', title: 'Retry', created_at: 3, updated_at: 4 }],
        job: { id: 'job-1', name: 'Morning Brief' },
      });

      expect(vi.mocked(fetch).mock.calls).toEqual([
        ['http://localhost:8000/api/scheduled-jobs/conversations'],
        ['http://localhost:8000/api/scheduled-jobs/job-1/conversations'],
      ]);
    });
  });

  describe('file browser API', () => {
    test('browses files with an optional query', async () => {
      const payload = {
        entries: [
          {
            name: 'README.md',
            path: '/repo/README.md',
            relative_path: 'README.md',
            is_directory: false,
            size: 123,
            extension: 'md',
          },
        ],
        current_path: '/repo',
        parent_path: null,
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(payload),
      });

      const result = await api.browseFiles('readme');

      expect(result).toEqual(payload);
      expect(fetch).toHaveBeenCalledWith('http://localhost:8000/api/files/browse?query=readme');
    });

    test('surfaces browse file errors with backend detail', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({ detail: 'Search root is unavailable' }),
      });

      await expect(api.browseFiles('docs')).rejects.toThrow('Search root is unavailable');
    });
  });

  describe('artifact auth headers', () => {
    const originalElectronApi = window.electronAPI;

    afterEach(() => {
      window.electronAPI = originalElectronApi;
    });

    test('adds the Electron server token header for artifact reads', async () => {
      window.electronAPI = {
        getServerToken: vi.fn().mockResolvedValue('artifact-token'),
      } as typeof window.electronAPI;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          artifacts: [],
          total: 0,
          page: 1,
          page_size: 50,
        }),
      });

      await api.listArtifacts();

      const [, init] = vi.mocked(fetch).mock.calls[0];
      expect(init).toBeDefined();
      expect((init?.headers as Headers).get('X-Xpdite-Server-Token')).toBe('artifact-token');
    });

    test('adds the Electron server token header and content type for artifact writes', async () => {
      window.electronAPI = {
        getServerToken: vi.fn().mockResolvedValue('artifact-token'),
      } as typeof window.electronAPI;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          id: 'artifact-1',
          type: 'code',
          title: 'demo.py',
          language: 'python',
          size_bytes: 11,
          line_count: 1,
          status: 'ready',
        }),
      });

      await api.createArtifact({
        type: 'code',
        title: 'demo.py',
        content: 'print("hi")',
        language: 'python',
      });

      const [, init] = vi.mocked(fetch).mock.calls[0];
      expect(init).toBeDefined();
      expect((init?.headers as Headers).get('X-Xpdite-Server-Token')).toBe('artifact-token');
      expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
    });
  });

  describe('marketplace API', () => {
    test('getMarketplaceCatalog returns catalog items', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          items: [{ manifest_item_id: 'planner-skill', kind: 'skill' }],
        }),
      });

      const result = await api.getMarketplaceCatalog();

      expect(result).toEqual([{ manifest_item_id: 'planner-skill', kind: 'skill' }]);
      const [url] = vi.mocked(fetch).mock.calls[0];
      expect(url).toBe('http://localhost:8000/api/marketplace/catalog');
    });

    test('installMarketplaceItem posts source, item, and secrets', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          install: { id: 'install-1', item_kind: 'skill' },
        }),
      });

      const result = await api.installMarketplaceItem({
        source_id: 'source-1',
        manifest_item_id: 'planner-skill',
        secrets: { API_TOKEN: 'secret' },
      });

      expect(result).toEqual({ id: 'install-1', item_kind: 'skill' });
      const [url, init] = vi.mocked(fetch).mock.calls[0];
      expect(url).toBe('http://localhost:8000/api/marketplace/install');
      expect(init?.method).toBe('POST');
      expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
      expect(init?.body).toBe(JSON.stringify({
        source_id: 'source-1',
        manifest_item_id: 'planner-skill',
        secrets: { API_TOKEN: 'secret' },
      }));
    });

    test('installMarketplacePackage posts runner and package command', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          install: { id: 'install-2', item_kind: 'mcp' },
        }),
      });

      const result = await api.installMarketplacePackage({
        runner: 'npx',
        package_input: '@modelcontextprotocol/server-everything --debug',
      });

      expect(result).toEqual({ id: 'install-2', item_kind: 'mcp' });
      const [url, init] = vi.mocked(fetch).mock.calls[0];
      expect(url).toBe('http://localhost:8000/api/marketplace/install-package');
      expect(init?.method).toBe('POST');
      expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
      expect(init?.body).toBe(JSON.stringify({
        runner: 'npx',
        package_input: '@modelcontextprotocol/server-everything --debug',
      }));
    });

    test('installMarketplaceRepo posts repo input', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          install: { id: 'install-3', item_kind: 'plugin' },
        }),
      });

      const result = await api.installMarketplaceRepo({
        repo_input: 'JuliusBrussee/caveman',
      });

      expect(result).toEqual({ id: 'install-3', item_kind: 'plugin' });
      const [url, init] = vi.mocked(fetch).mock.calls[0];
      expect(url).toBe('http://localhost:8000/api/marketplace/install-repo');
      expect(init?.method).toBe('POST');
      expect((init?.headers as Headers).get('Content-Type')).toBe('application/json');
      expect(init?.body).toBe(JSON.stringify({
        repo_input: 'JuliusBrussee/caveman',
      }));
    });

    test('marketplace requests include the Electron server token header', async () => {
      window.electronAPI = {
        getServerToken: vi.fn().mockResolvedValue('marketplace-token'),
      } as typeof window.electronAPI;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ items: [] }),
      });

      await api.getMarketplaceCatalog();

      const [, init] = vi.mocked(fetch).mock.calls[0];
      expect((init?.headers as Headers).get('X-Xpdite-Server-Token')).toBe('marketplace-token');
    });
  });
});
