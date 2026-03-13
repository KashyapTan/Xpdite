/**
 * API Service.
 * 
 * Abstraction layer for communicating with the Python backend.
 * Currently uses WebSocket, but can be extended to support HTTP REST APIs.
 * 
 * ## How to Add a New API Endpoint
 * 
 * ### For WebSocket-based APIs (real-time, bidirectional):
 * 
 * 1. Add a new method to this ApiService class
 * 2. The method should call `this.send()` with the appropriate message type
 * 3. Handle the response in the WebSocket message handler (useWebSocket hook)
 * 
 * ### For HTTP REST APIs (request/response, one-time):
 * 
 * 1. Add a new method that uses fetch() to call your Python endpoint
 * 2. In Python, add a new route in `source/api/http.py` (create if needed)
 * 3. Register the route in `source/app.py`
 * 
 * ### Example: Adding an HTTP REST API
 * 
 * **Frontend (this file):**
 * ```typescript
 * async getModels(): Promise<string[]> {
 *   const response = await fetch(`${HTTP_BASE_URL}/api/models`);
 *   return response.json();
 * }
 * ```
 * 
 * **Backend (source/api/http.py):**
 * ```python
 * from fastapi import APIRouter
 * 
 * router = APIRouter(prefix="/api")
 * 
 * @router.get("/models")
 * async def get_models():
 *     return ["qwen3-vl:8b-instruct", "llama3.2"]
 * ```
 * 
 * **Register in app.py:**
 * ```python
 * from .api.http import router as http_router
 * app.include_router(http_router)
 * ```
 */

import { discoverServerPort, getHttpBaseUrl, getWsBaseUrl } from './portDiscovery';
import type { Skill } from '../types';

/**
 * Awaits port discovery (cached after first call) and returns the HTTP base URL.
 * Every async `api.*` method calls this so even the earliest request waits
 * for the server port to be resolved before firing.
 */
async function baseUrl(): Promise<string> {
  await discoverServerPort();
  return getHttpBaseUrl();
}

export type CloudProvider = 'anthropic' | 'openai' | 'gemini' | 'openrouter';

export interface ProviderModel {
  id: string;
  provider: string;
  display_name: string;
  provider_group?: string;
  context_length?: number;
}

interface RawProviderModel {
  id?: unknown;
  name?: unknown;
  provider?: unknown;
  display_name?: unknown;
  description?: unknown;
  provider_group?: unknown;
  context_length?: unknown;
}

function normalizeProviderModel(provider: string, rawModel: RawProviderModel): ProviderModel | null {
  const id = typeof rawModel.id === 'string'
    ? rawModel.id
    : typeof rawModel.name === 'string'
      ? rawModel.name
      : '';

  if (!id) {
    return null;
  }

  const displayName = typeof rawModel.display_name === 'string'
    ? rawModel.display_name
    : typeof rawModel.description === 'string'
      ? rawModel.description
      : id;

  return {
    id,
    provider: typeof rawModel.provider === 'string' ? rawModel.provider : provider,
    display_name: displayName,
    provider_group: typeof rawModel.provider_group === 'string' ? rawModel.provider_group : undefined,
    context_length: typeof rawModel.context_length === 'number' ? rawModel.context_length : undefined,
  };
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  const body = await response.json().catch(() => ({ detail: fallback }));
  if (typeof body?.detail === 'string' && body.detail.trim()) {
    return body.detail;
  }
  if (typeof body?.message === 'string' && body.message.trim()) {
    return body.message;
  }
  return fallback;
}

export interface ApiService {
  // WebSocket methods
  submitQuery: (query: string, captureMode: string) => void;
  clearContext: () => void;
  removeScreenshot: (id: string) => void;
  setCaptureMode: (mode: string) => void;
  stopStreaming: () => void;
  cancelQueuedItem: (itemId: string) => void;
  getConversations: (limit?: number, offset?: number) => void;
  searchConversations: (query: string) => void;
  resumeConversation: (conversationId: string) => void;
  deleteConversation: (conversationId: string) => void;
  tabCreated: (tabId: string) => void;
  tabClosed: (tabId: string) => void;
  tabActivated: (tabId: string) => void;
  // Meeting recording methods
  startMeetingRecording: () => void;
  stopMeetingRecording: () => void;
  getMeetingRecordings: (limit?: number, offset?: number) => void;
  searchMeetingRecordings: (query: string) => void;
  deleteMeetingRecording: (id: string) => void;
  getMeetingRecordingStatus: () => void;
}

/**
 * Creates an API service bound to a WebSocket send function.
 *
 * All messages are stamped with ``tab_id`` via the ``getTabId`` callback
 * so the backend can route them to the correct tab session.
 */
export function createApiService(
  send: (message: Record<string, unknown>) => void,
  getTabId: () => string = () => 'default',
): ApiService {
  /** Helper: send with auto-injected tab_id. */
  const tabSend = (msg: Record<string, unknown>) => send({ ...msg, tab_id: getTabId() });

  return {
    submitQuery(query: string, captureMode: string) {
      tabSend({
        type: 'submit_query',
        content: query,
        capture_mode: captureMode,
      });
    },

    clearContext() {
      tabSend({ type: 'clear_context' });
    },

    removeScreenshot(id: string) {
      tabSend({ type: 'remove_screenshot', id });
    },

    setCaptureMode(mode: string) {
      tabSend({ type: 'set_capture_mode', mode });
    },

    stopStreaming() {
      tabSend({ type: 'stop_streaming' });
    },

    cancelQueuedItem(itemId: string) {
      tabSend({ type: 'cancel_queued_item', item_id: itemId });
    },

    getConversations(limit = 50, offset = 0) {
      send({ type: 'get_conversations', limit, offset });
    },

    searchConversations(query: string) {
      send({ type: 'search_conversations', query });
    },

    resumeConversation(conversationId: string) {
      tabSend({ type: 'resume_conversation', conversation_id: conversationId });
    },

    deleteConversation(conversationId: string) {
      send({ type: 'delete_conversation', conversation_id: conversationId });
    },

    tabCreated(tabId: string) {
      send({ type: 'tab_created', tab_id: tabId });
    },

    tabClosed(tabId: string) {
      send({ type: 'tab_closed', tab_id: tabId });
    },

    tabActivated(tabId: string) {
      send({ type: 'tab_activated', tab_id: tabId });
    },

    // Meeting recording methods
    startMeetingRecording() {
      send({ type: 'meeting_start_recording' });
    },

    stopMeetingRecording() {
      send({ type: 'meeting_stop_recording' });
    },

    getMeetingRecordings(limit = 50, offset = 0) {
      send({ type: 'get_meeting_recordings', limit, offset });
    },

    searchMeetingRecordings(query: string) {
      send({ type: 'search_meeting_recordings', query });
    },

    deleteMeetingRecording(id: string) {
      send({ type: 'delete_meeting_recording', recording_id: id });
    },

    getMeetingRecordingStatus() {
      send({ type: 'meeting_get_status' });
    },

    // HTTP API examples (uncomment and implement as needed):
    // async getModels() {
    //   const response = await fetch(`${HTTP_BASE_URL}/api/models`);
    //   if (!response.ok) throw new Error('Failed to fetch models');
    //   return response.json();
    // },
    //
    // async getHealth() {
    //   const response = await fetch(`${HTTP_BASE_URL}/health`);
    //   if (!response.ok) throw new Error('Health check failed');
    //   return response.json();
    // },
  };
}

// Singleton for direct imports (when WebSocket context is not needed)
export const api = {
  /**
   * Current HTTP base URL. **Synchronous** — returns `http://localhost:8000`
   * until `discoverServerPort()` has resolved. Prefer `await baseUrl()`
   * inside async methods to guarantee the correct port.
   */
  get HTTP_BASE_URL() { return getHttpBaseUrl(); },
  /** @see HTTP_BASE_URL — same caveat about pre-discovery staleness. */
  get WS_BASE_URL() { return getWsBaseUrl(); },

  /**
   * Fetch all Ollama models installed on the user's machine.
   * Calls GET /api/models/ollama on the Python backend,
   * which in turn calls `ollama.list()`.
   *
   * Returns { models, error? } — when Ollama is unreachable the backend
   * sends `{ models: [], error: "..." }` so we surface the message.
   */
  async getOllamaModels(refresh = false): Promise<{ models: { name: string; size: number; parameter_size: string; quantization: string }[]; error?: string }> {
    try {
      const base = await baseUrl();
      const url = new URL(`${base}/api/models/ollama`);
      if (refresh) {
        url.searchParams.set('refresh', 'true');
      }
      const response = await fetch(url.toString());
      if (!response.ok) throw new Error('Failed to fetch Ollama models');
      const data = await response.json();
      // Backend may return { models: [...], error: "..." } or just an array
      if (Array.isArray(data)) {
        return { models: data };
      }
      return { models: data.models ?? [], error: data.error };
    } catch {
      return { models: [] };
    }
  },

  /**
   * Fetch the list of model names the user has toggled on.
   * Calls GET /api/models/enabled which reads from the SQLite settings table.
   */
  async getEnabledModels(): Promise<string[]> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/models/enabled`);
      if (!response.ok) throw new Error('Failed to fetch enabled models');
      return response.json();
    } catch {
      return [];
    }
  },

  /**
   * Save the full list of enabled model names.
   * Calls PUT /api/models/enabled which writes to the SQLite settings table.
   */
  async setEnabledModels(models: string[]): Promise<void> {
    try {
      const base = await baseUrl();
      await fetch(`${base}/api/models/enabled`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ models }),
      });
    } catch {
      console.error('Failed to save enabled models');
    }
  },

  /**
   * Check if the server is healthy.
   */
  async healthCheck(): Promise<boolean> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/health`);
      return response.ok;
    } catch {
      return false;
    }
  },

  // ============================================
  // API Key Management
  // ============================================

  /**
   * Get status of all provider API keys.
   * Returns {provider: {has_key: boolean, masked: string|null}} for each provider.
   */
  async getApiKeyStatus(): Promise<Record<string, { has_key: boolean; masked: string | null }>> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/keys`);
      if (!response.ok) throw new Error('Failed to fetch API key status');
      return response.json();
    } catch {
      return {};
    }
  },

  /**
   * Save an API key for a provider. Validates the key on the backend before storing.
   * Returns {status, provider, masked} on success.
   * Throws an error with the validation message on failure.
   */
  async saveApiKey(provider: string, key: string): Promise<{ status: string; provider: string; masked: string }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/keys/${provider}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Failed to save API key' }));
      throw new Error(error.detail || 'Failed to save API key');
    }
    return response.json();
  },

  /**
   * Delete a stored API key for a provider.
   */
  async deleteApiKey(provider: string): Promise<void> {
    try {
      const base = await baseUrl();
      await fetch(`${base}/api/keys/${provider}`, {
        method: 'DELETE',
      });
    } catch {
      console.error(`Failed to delete API key for ${provider}`);
    }
  },

  // ============================================
  // Cloud Provider Models
  // ============================================

  /**
   * Fetch available models for a cloud provider.
   * Supports cache-busting fetches when refresh=true.
   */
  async getProviderModels(provider: CloudProvider, refresh = false): Promise<ProviderModel[]> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/models/${provider}`);
    if (refresh) {
      url.searchParams.set('refresh', 'true');
    }
    const response = await fetch(url.toString());

    if (!response.ok) {
      const detail = await readErrorDetail(response, `Failed to fetch ${provider} models`);
      throw new Error(detail);
    }

    const payload = await response.json();
    if (!Array.isArray(payload)) {
      return [];
    }

    const normalized = payload
      .map((rawModel) => normalizeProviderModel(provider, rawModel as RawProviderModel))
      .filter((model): model is ProviderModel => model !== null);

    return normalized;
  },

  // ============================================
  // Google OAuth Connection
  // ============================================

  /**
   * Get the current Google account connection status.
   * Returns {connected, email, auth_in_progress}.
   */
  async getGoogleStatus(): Promise<{
    connected: boolean;
    email: string | null;
    auth_in_progress: boolean;
  }> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/google/status`);
      if (!response.ok) throw new Error('Failed to get Google status');
      return response.json();
    } catch {
      return { connected: false, email: null, auth_in_progress: false };
    }
  },

  /**
   * Initiate Google OAuth flow. Opens the user's browser for Google login.
   * This is a blocking call that waits for the OAuth callback.
   */
  async connectGoogle(): Promise<{ success: boolean; email?: string; error?: string }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/google/connect`, {
      method: 'POST',
    });
    if (!response.ok) {
      // Backend returns {detail: "..."} for HTTP errors
      const body = await response.json().catch(() => ({ detail: 'Connection failed' }));
      return { success: false, error: body.detail || 'Connection failed' };
    }
    return response.json();
  },

  /**
   * Disconnect Google account. Revokes token, removes token file,
   * and stops Gmail/Calendar MCP servers.
   */
  async disconnectGoogle(): Promise<{ success: boolean; error?: string }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/google/disconnect`, {
      method: 'POST',
    });
    return response.json();
  },

  // ============================================
  // MCP Tools
  // ============================================

  /**
   * Get connected MCP servers and their tools.
   */
  async getMcpServers(): Promise<{ server: string; tools: string[] }[]> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/mcp/servers`);
      if (!response.ok) throw new Error('Failed to fetch MCP servers');
      return response.json();
    } catch {
      return [];
    }
  },

  /**
   * Get tool retrieval settings (always_on, top_k).
   */
  async getToolsSettings(): Promise<{ always_on: string[]; top_k: number }> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/settings/tools`);
      if (!response.ok) throw new Error('Failed to fetch tool settings');
      return response.json();
    } catch {
      return { always_on: [], top_k: 5 };
    }
  },

  /**
   * Update tool retrieval settings.
   */
  async setToolsSettings(alwaysOn: string[], topK: number): Promise<void> {
    try {
      const base = await baseUrl();
      await fetch(`${base}/api/settings/tools`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ always_on: alwaysOn, top_k: topK }),
      });
    } catch {
      console.error('Failed to save tool settings');
    }
  },

  // ============================================
  // Sub-Agent Settings
  // ============================================

  async getSubAgentSettings(): Promise<{ fast_model: string; smart_model: string }> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/settings/sub-agents`);
      if (!response.ok) throw new Error('Failed to fetch sub-agent settings');
      return response.json();
    } catch {
      return { fast_model: '', smart_model: '' };
    }
  },

  async setSubAgentSettings(settings: { fast_model: string; smart_model: string }): Promise<void> {
    const base = await baseUrl();
    await fetch(`${base}/api/settings/sub-agents`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
  },

  // ============================================
  // System Prompt
  // ============================================

  /**
   * Get the custom system prompt template.
   */
  async getSystemPrompt(): Promise<{ template: string; is_custom: boolean }> {
    const base = await baseUrl();
    const res = await fetch(`${base}/api/settings/system-prompt`);
    if (!res.ok) throw new Error('Failed to fetch system prompt');
    return res.json();
  },

  /**
   * Save a custom system prompt template.
   */
  async setSystemPrompt(template: string): Promise<void> {
    const base = await baseUrl();
    const res = await fetch(`${base}/api/settings/system-prompt`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template }),
    });
    if (!res.ok) throw new Error('Failed to save system prompt');
  },

  // ============================================
  // Skills API
  // ============================================

  skillsApi: {
    async getAll(): Promise<Skill[]> {
      const base = await baseUrl();
      const res = await fetch(`${base}/api/skills`);
      if (!res.ok) throw new Error('Failed to fetch skills');
      return res.json();
    },

    async getContent(name: string): Promise<string> {
      const base = await baseUrl();
      const res = await fetch(`${base}/api/skills/${name}/content`);
      if (!res.ok) throw new Error('Failed to fetch skill content');
      const data = await res.json();
      return data.content;
    },

    async create(skill: { name: string; description: string; slash_command?: string; content: string; trigger_servers?: string[] }): Promise<void> {
      const base = await baseUrl();
      const res = await fetch(`${base}/api/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(skill),
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to create skill' }));
        throw new Error(error.detail || 'Failed to create skill');
      }
    },

    async update(name: string, update: { description?: string; slash_command?: string; content?: string; trigger_servers?: string[] }): Promise<void> {
      const base = await baseUrl();
      const res = await fetch(`${base}/api/skills/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to update skill' }));
        throw new Error(error.detail || 'Failed to update skill');
      }
    },

    async toggle(name: string, enabled: boolean): Promise<void> {
      const base = await baseUrl();
      const res = await fetch(`${base}/api/skills/${name}/toggle`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error('Failed to toggle skill');
    },

    async delete(name: string): Promise<void> {
      const base = await baseUrl();
      const res = await fetch(`${base}/api/skills/${name}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to delete skill');
    },
  }
};
