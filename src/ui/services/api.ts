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

const WS_BASE_URL = 'ws://localhost:8000';
const HTTP_BASE_URL = 'http://localhost:8000';

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
  HTTP_BASE_URL,
  WS_BASE_URL,

  /**
   * Fetch all Ollama models installed on the user's machine.
   * Calls GET /api/models/ollama on the Python backend,
   * which in turn calls `ollama.list()`.
   *
   * Returns { models, error? } — when Ollama is unreachable the backend
   * sends `{ models: [], error: "..." }` so we surface the message.
   */
  async getOllamaModels(): Promise<{ models: { name: string; size: number; parameter_size: string; quantization: string }[]; error?: string }> {
    try {
      const response = await fetch(`${HTTP_BASE_URL}/api/models/ollama`);
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
      const response = await fetch(`${HTTP_BASE_URL}/api/models/enabled`);
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
      await fetch(`${HTTP_BASE_URL}/api/models/enabled`, {
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
      const response = await fetch(`${HTTP_BASE_URL}/health`);
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
      const response = await fetch(`${HTTP_BASE_URL}/api/keys`);
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
    const response = await fetch(`${HTTP_BASE_URL}/api/keys/${provider}`, {
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
      await fetch(`${HTTP_BASE_URL}/api/keys/${provider}`, {
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
   * Returns models with provider prefix (e.g., "anthropic/claude-sonnet-4-20250514").
   */
  async getProviderModels(provider: string): Promise<{ name: string; provider: string; description: string }[]> {
    try {
      const response = await fetch(`${HTTP_BASE_URL}/api/models/${provider}`);
      if (!response.ok) throw new Error(`Failed to fetch ${provider} models`);
      return response.json();
    } catch {
      return [];
    }
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
      const response = await fetch(`${HTTP_BASE_URL}/api/google/status`);
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
    const response = await fetch(`${HTTP_BASE_URL}/api/google/connect`, {
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
    const response = await fetch(`${HTTP_BASE_URL}/api/google/disconnect`, {
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
      const response = await fetch(`${HTTP_BASE_URL}/api/mcp/servers`);
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
      const response = await fetch(`${HTTP_BASE_URL}/api/settings/tools`);
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
      await fetch(`${HTTP_BASE_URL}/api/settings/tools`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ always_on: alwaysOn, top_k: topK }),
      });
    } catch {
      console.error('Failed to save tool settings');
    }
  },

  // ============================================
  // System Prompt
  // ============================================

  /**
   * Get the custom system prompt template.
   */
  async getSystemPrompt(): Promise<{ template: string; is_custom: boolean }> {
    const res = await fetch(`${HTTP_BASE_URL}/api/settings/system-prompt`);
    if (!res.ok) throw new Error('Failed to fetch system prompt');
    return res.json();
  },

  /**
   * Save a custom system prompt template.
   */
  async setSystemPrompt(template: string): Promise<void> {
    const res = await fetch(`${HTTP_BASE_URL}/api/settings/system-prompt`, {
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
    async getAll(): Promise<any[]> {
      const res = await fetch(`${HTTP_BASE_URL}/api/skills`);
      if (!res.ok) throw new Error('Failed to fetch skills');
      return res.json();
    },

    async create(skill: { skill_name: string; display_name: string; slash_command: string; content: string; enabled: boolean }): Promise<void> {
      const res = await fetch(`${HTTP_BASE_URL}/api/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(skill),
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to create skill' }));
        throw new Error(error.detail || 'Failed to create skill');
      }
    },

    async update(skillName: string, update: { display_name: string; slash_command: string; content: string; enabled: boolean }): Promise<void> {
      const res = await fetch(`${HTTP_BASE_URL}/api/skills/${skillName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(update),
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Failed to update skill' }));
        throw new Error(error.detail || 'Failed to update skill');
      }
    },

    async delete(skillName: string): Promise<void> {
      const res = await fetch(`${HTTP_BASE_URL}/api/skills/${skillName}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to delete skill');
    },

    async reset(skillName: string): Promise<void> {
      const res = await fetch(`${HTTP_BASE_URL}/api/skills/${skillName}/reset`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to reset skill');
    },
  }
};
