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
import type {
  ArtifactKind,
  ArtifactStatus,
  MemoryDetail,
  MemorySettings,
  MemorySummary,
  Skill,
} from '../types';

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

export interface OllamaModel {
  name: string;
  size: number;
  parameter_size: string;
  quantization: string;
  source?: 'installed' | 'custom';
  is_local?: boolean;
}

export interface OllamaRegistryLayerInfo {
  media_type: string;
  digest?: string;
  size: number;
  type: string;
}

export interface OllamaRegistryModelInfo {
  name: string;
  tag: string;
  full_name: string;
  family: string;
  families: string[];
  parameter_size: string;
  quantization: string;
  format: string;
  architecture: string;
  os: string;
  total_size_bytes: number;
  total_size_human: string;
  config_size_bytes: number;
  layers: OllamaRegistryLayerInfo[];
  manifest_url: string;
  config_url: string;
  is_installed: boolean;
}

export interface OllamaRegistryModelInfoResponse {
  success: boolean;
  data?: OllamaRegistryModelInfo;
  error?: string;
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

/**
 * External MCP connector status from backend.
 */
export interface ExternalConnector {
  name: string;
  display_name: string;
  description: string;
  services: string[];
  icon_type: string;
  auth_type: 'browser' | null;
  enabled: boolean;
  connected: boolean;
  last_error: string | null;
}

/**
 * Response from connect external connector endpoint.
 */
export interface ConnectExternalConnectorResponse {
  success: boolean;
  error?: string;
}

/**
 * File entry from the file browser API.
 */
export interface FileEntry {
  name: string;
  path: string;
  relative_path: string;
  is_directory: boolean;
  size: number | null;
  extension: string | null;
}

export interface ArtifactRecord {
  id: string;
  type: ArtifactKind;
  title: string;
  language?: string;
  content?: string;
  sizeBytes: number;
  lineCount: number;
  status: ArtifactStatus;
  conversationId?: string | null;
  messageId?: string | null;
  createdAt?: number;
  updatedAt?: number;
}

interface RawArtifactRecord {
  id: string;
  type: ArtifactKind;
  title: string;
  language?: string | null;
  content?: string;
  size_bytes: number;
  line_count: number;
  status: ArtifactStatus;
  conversation_id?: string | null;
  message_id?: string | null;
  created_at?: number;
  updated_at?: number;
}

export interface ArtifactListResponse {
  artifacts: ArtifactRecord[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ArtifactListOptions {
  query?: string;
  type?: ArtifactKind;
  status?: Exclude<ArtifactStatus, 'streaming'>;
  page?: number;
  pageSize?: number;
}

function normalizeArtifact(raw: RawArtifactRecord): ArtifactRecord {
  return {
    id: raw.id,
    type: raw.type,
    title: raw.title,
    language: raw.language ?? undefined,
    content: raw.content,
    sizeBytes: raw.size_bytes ?? 0,
    lineCount: raw.line_count ?? 0,
    status: raw.status,
    conversationId: raw.conversation_id,
    messageId: raw.message_id,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
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
  // Ollama model management
  pullOllamaModel: (modelName: string) => void;
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

    // Ollama model management
    pullOllamaModel(modelName: string) {
      send({ type: 'ollama_pull_model', model_name: modelName });
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
   * which in turn lists locally installed models and merges any enabled
   * custom Ollama IDs so env-driven cloud/remote models stay selectable.
   *
   * Returns { models, error? } — when Ollama is unreachable the backend
   * sends `{ models: [], error: "..." }` so we surface the message.
   */
  async getOllamaModels(refresh = false): Promise<{ models: OllamaModel[]; error?: string }> {
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
  // Memory Settings and Files
  // ============================================

  async getMemorySettings(): Promise<MemorySettings> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/settings/memory`);
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to fetch memory settings');
      throw new Error(detail);
    }
    return response.json();
  },

  async setMemorySettings(settings: MemorySettings): Promise<void> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/settings/memory`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
    if (!response.ok) {
      throw new Error('Failed to save memory settings');
    }
  },

  /**
   * Fetch registry metadata for an Ollama model without pulling full weights.
   */
  async getOllamaModelInfo(modelName: string): Promise<OllamaRegistryModelInfoResponse> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/models/ollama/info/${encodeURIComponent(modelName)}`);
      if (!response.ok) {
        return {
          success: false,
          error: 'Failed to fetch model info',
        };
      }
      const data = await response.json();
      if (typeof data?.success === 'boolean') {
        return data as OllamaRegistryModelInfoResponse;
      }
      return {
        success: false,
        error: 'Invalid model info response',
      };
    } catch {
      return {
        success: false,
        error: 'Failed to fetch model info',
      };
    }
  },

  async listMemories(folder?: string): Promise<MemorySummary[]> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/memory`);
    if (folder) {
      url.searchParams.set('folder', folder);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error('Failed to fetch memories');
    }
    const payload = await response.json();
    return Array.isArray(payload?.memories) ? payload.memories : [];
  },

  async getMemory(path: string): Promise<MemoryDetail> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/memory/file`);
    url.searchParams.set('path', path);
    const response = await fetch(url.toString());
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to fetch memory');
      throw new Error(detail);
    }
    return response.json();
  },

  async updateMemory(memory: {
    path: string;
    title: string;
    category: string;
    importance: number;
    tags: string[];
    abstract: string;
    body: string;
  }): Promise<MemoryDetail> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/memory/file`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(memory),
    });
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to save memory');
      throw new Error(detail);
    }
    return response.json();
  },

  async deleteMemory(path: string): Promise<void> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/memory/file`);
    url.searchParams.set('path', path);
    const response = await fetch(url.toString(), {
      method: 'DELETE',
    });
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to delete memory');
      throw new Error(detail);
    }
  },

  async clearAllMemories(): Promise<{ success: boolean; deleted_count: number }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/memory`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error('Failed to clear memories');
    }
    return response.json();
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
  // Artifacts API
  // ============================================

  async listArtifacts(options: ArtifactListOptions = {}): Promise<ArtifactListResponse> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/artifacts`);
    if (options.query) {
      url.searchParams.set('query', options.query);
    }
    if (options.type) {
      url.searchParams.set('type', options.type);
    }
    if (options.status) {
      url.searchParams.set('status', options.status);
    }
    if (options.page) {
      url.searchParams.set('page', String(options.page));
    }
    if (options.pageSize) {
      url.searchParams.set('page_size', String(options.pageSize));
    }

    const response = await fetch(url.toString());
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to fetch artifacts');
      throw new Error(detail);
    }

    const payload = await response.json();
    return {
      artifacts: Array.isArray(payload?.artifacts)
        ? payload.artifacts.map((artifact: RawArtifactRecord) => normalizeArtifact(artifact))
        : [],
      total: typeof payload?.total === 'number' ? payload.total : 0,
      page: typeof payload?.page === 'number' ? payload.page : 1,
      pageSize: typeof payload?.page_size === 'number' ? payload.page_size : (options.pageSize ?? 50),
    };
  },

  async getArtifactsForConversation(
    conversationId: string,
    options: ArtifactListOptions = {},
  ): Promise<ArtifactListResponse> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/artifacts/conversation/${encodeURIComponent(conversationId)}`);
    if (options.query) {
      url.searchParams.set('query', options.query);
    }
    if (options.type) {
      url.searchParams.set('type', options.type);
    }
    if (options.status) {
      url.searchParams.set('status', options.status);
    }
    if (options.page) {
      url.searchParams.set('page', String(options.page));
    }
    if (options.pageSize) {
      url.searchParams.set('page_size', String(options.pageSize));
    }

    const response = await fetch(url.toString());
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to fetch conversation artifacts');
      throw new Error(detail);
    }

    const payload = await response.json();
    return {
      artifacts: Array.isArray(payload?.artifacts)
        ? payload.artifacts.map((artifact: RawArtifactRecord) => normalizeArtifact(artifact))
        : [],
      total: typeof payload?.total === 'number' ? payload.total : 0,
      page: typeof payload?.page === 'number' ? payload.page : 1,
      pageSize: typeof payload?.page_size === 'number' ? payload.page_size : (options.pageSize ?? 50),
    };
  },

  async getArtifact(artifactId: string): Promise<ArtifactRecord> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/artifacts/${encodeURIComponent(artifactId)}`);
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to fetch artifact');
      throw new Error(detail);
    }
    const payload = await response.json();
    return normalizeArtifact(payload as RawArtifactRecord);
  },

  async createArtifact(input: {
    type: ArtifactKind;
    title: string;
    content: string;
    language?: string;
    conversationId?: string | null;
    messageId?: string | null;
  }): Promise<ArtifactRecord> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/artifacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: input.type,
        title: input.title,
        content: input.content,
        language: input.language,
        conversation_id: input.conversationId,
        message_id: input.messageId,
      }),
    });
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to create artifact');
      throw new Error(detail);
    }
    return normalizeArtifact(await response.json() as RawArtifactRecord);
  },

  async updateArtifact(
    artifactId: string,
    updates: {
      title?: string;
      content?: string;
      language?: string;
    },
  ): Promise<ArtifactRecord> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/artifacts/${encodeURIComponent(artifactId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to update artifact');
      throw new Error(detail);
    }
    return normalizeArtifact(await response.json() as RawArtifactRecord);
  },

  async deleteArtifact(artifactId: string): Promise<void> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/artifacts/${encodeURIComponent(artifactId)}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to delete artifact');
      throw new Error(detail);
    }
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
  },

  // ============================================
  // External Connectors API
  // ============================================

  /**
   * Get all available external connectors with their status.
   */
  async getExternalConnectors(): Promise<ExternalConnector[]> {
    try {
      const base = await baseUrl();
      const response = await fetch(`${base}/api/external-connectors`);
      if (!response.ok) throw new Error('Failed to fetch external connectors');
      return response.json();
    } catch {
      return [];
    }
  },

  /**
   * Connect an external MCP connector.
   * For browser-auth connectors, this may open a browser window.
   */
  async connectExternalConnector(name: string): Promise<{ success: boolean; error?: string }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/external-connectors/${name}/connect`, {
      method: 'POST',
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: 'Connection failed' }));
      return { success: false, error: body.detail || 'Connection failed' };
    }
    return response.json();
  },

  /**
   * Disconnect an external MCP connector.
   */
  async disconnectExternalConnector(name: string): Promise<{ success: boolean; error?: string }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/external-connectors/${name}/disconnect`, {
      method: 'POST',
    });
    return response.json();
  },

  // ============================================
  // Mobile Channels API
  // ============================================

  /**
   * Get all paired mobile devices.
   */
  async getMobilePairedDevices(): Promise<{ devices: Array<{
    id: number;
    platform: string;
    sender_id: string;
    display_name: string | null;
    paired_at: number;
    last_active: number | null;
  }> }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/internal/mobile/devices`);
    if (!response.ok) throw new Error('Failed to fetch paired devices');
    return response.json();
  },

  /**
   * Generate a new pairing code.
   */
  async generateMobilePairingCode(): Promise<{ code: string; expires_in_seconds: number }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/internal/mobile/pair/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expires_in_seconds: 600 }),
    });
    if (!response.ok) throw new Error('Failed to generate pairing code');
    return response.json();
  },

  /**
   * Revoke a paired device.
   */
  async revokeMobilePairedDevice(deviceId: number): Promise<void> {
    const base = await baseUrl();
    const response = await fetch(`${base}/internal/mobile/devices/${deviceId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Failed to revoke device');
  },

  /**
   * Get mobile channels configuration.
   */
  async getMobileChannelsConfig(): Promise<{
    platforms?: Record<string, {
      enabled: boolean;
      token?: string;
      status: 'connected' | 'disconnected' | 'error';
    }>;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/mobile-channels/config`);
    if (!response.ok) {
      // Return empty config if not found
      return { platforms: {} };
    }
    return response.json();
  },

  /**
   * Set configuration for a mobile platform.
   */
  async setMobilePlatformConfig(
    platformId: string,
    config: { token?: string; enabled?: boolean; phoneNumber?: string; authMethod?: string; forcePairing?: boolean }
  ): Promise<void> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/mobile-channels/config/${platformId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    if (!response.ok) throw new Error('Failed to save platform config');
  },

  // ============================================
  // Notifications API
  // ============================================

  /**
   * Get all notifications.
   */
  async getNotifications(): Promise<{
    notifications: Array<{
      id: string;
      type: string;
      title: string;
      body: string;
      payload: Record<string, unknown> | null;
      created_at: number;
    }>;
    unread_count: number;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/notifications`);
    if (!response.ok) throw new Error('Failed to fetch notifications');
    return response.json();
  },

  /**
   * Get notification count.
   */
  async getNotificationCount(): Promise<{ count: number }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/notifications/count`);
    if (!response.ok) throw new Error('Failed to fetch notification count');
    return response.json();
  },

  /**
   * Dismiss a single notification.
   */
  async dismissNotification(notificationId: string): Promise<void> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/notifications/${notificationId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Failed to dismiss notification');
  },

  /**
   * Dismiss all notifications.
   */
  async dismissAllNotifications(): Promise<{ dismissed_count: number }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/notifications`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Failed to dismiss notifications');
    return response.json();
  },

  // ============================================
  // Scheduled Jobs API
  // ============================================

  /**
   * Get all scheduled jobs.
   */
  async getScheduledJobs(): Promise<{
    jobs: Array<{
      id: string;
      name: string;
      cron_expression: string;
      instruction: string;
      model: string | null;
      timezone: string;
      delivery_platform: string | null;
      delivery_sender_id: string | null;
      enabled: boolean;
      is_one_shot: boolean;
      created_at: number;
      last_run_at: number | null;
      next_run_at: number | null;
      run_count: number;
      missed: boolean;
    }>;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs`);
    if (!response.ok) throw new Error('Failed to fetch scheduled jobs');
    return response.json();
  },

  /**
   * Get a specific scheduled job.
   */
  async getScheduledJob(jobId: string): Promise<{
    id: string;
    name: string;
    cron_expression: string;
    instruction: string;
    model: string | null;
    timezone: string;
    delivery_platform: string | null;
    delivery_sender_id: string | null;
    enabled: boolean;
    is_one_shot: boolean;
    created_at: number;
    last_run_at: number | null;
    next_run_at: number | null;
    run_count: number;
    missed: boolean;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}`);
    if (!response.ok) throw new Error('Failed to fetch scheduled job');
    return response.json();
  },

  /**
   * Create a new scheduled job.
   */
  async createScheduledJob(job: {
    name: string;
    cron_expression: string;
    instruction: string;
    timezone: string;
    model?: string;
    delivery_platform?: string;
    delivery_sender_id?: string;
    is_one_shot?: boolean;
  }): Promise<{
    id: string;
    name: string;
    cron_expression: string;
    instruction: string;
    timezone: string;
    model: string | null;
    delivery_platform: string | null;
    delivery_sender_id: string | null;
    enabled: boolean;
    is_one_shot: boolean;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(job),
    });
    if (!response.ok) throw new Error('Failed to create scheduled job');
    return response.json();
  },

  /**
   * Update a scheduled job.
   */
  async updateScheduledJob(jobId: string, updates: {
    name?: string;
    cron_expression?: string;
    instruction?: string;
    timezone?: string;
    model?: string;
    delivery_platform?: string;
    delivery_sender_id?: string;
    enabled?: boolean;
    is_one_shot?: boolean;
  }): Promise<{
    id: string;
    name: string;
    cron_expression: string;
    instruction: string;
    timezone: string;
    model: string | null;
    enabled: boolean;
    is_one_shot: boolean;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (!response.ok) throw new Error('Failed to update scheduled job');
    return response.json();
  },

  /**
   * Delete a scheduled job.
   */
  async deleteScheduledJob(jobId: string): Promise<void> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error('Failed to delete scheduled job');
  },

  /**
   * Pause a scheduled job.
   */
  async pauseScheduledJob(jobId: string): Promise<{
    id: string;
    name: string;
    enabled: boolean;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}/pause`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to pause scheduled job');
    return response.json();
  },

  /**
   * Resume a scheduled job.
   */
  async resumeScheduledJob(jobId: string): Promise<{
    id: string;
    name: string;
    enabled: boolean;
    next_run_at: number | null;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}/resume`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to resume scheduled job');
    return response.json();
  },

  /**
   * Run a scheduled job immediately.
   */
  async runScheduledJobNow(jobId: string): Promise<{
    success: boolean;
    conversation_id: string | null;
    job_name: string;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}/run-now`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to run scheduled job');
    return response.json();
  },

  /**
   * Get all conversations created by scheduled jobs.
   */
  async getScheduledJobConversations(): Promise<{
    conversations: Array<{
      id: string;
      job_id: string;
      job_name: string | null;
      title: string;
      created_at: number;
      updated_at: number;
    }>;
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/conversations`);
    if (!response.ok) throw new Error('Failed to fetch job conversations');
    return response.json();
  },

  /**
   * Get conversations for a specific scheduled job.
   */
  async getJobConversations(jobId: string): Promise<{
    conversations: Array<{
      id: string;
      job_id: string;
      job_name: string | null;
      title: string;
      created_at: number;
      updated_at: number;
    }>;
    job: {
      id: string;
      name: string;
    };
  }> {
    const base = await baseUrl();
    const response = await fetch(`${base}/api/scheduled-jobs/${jobId}/conversations`);
    if (!response.ok) throw new Error('Failed to fetch job conversations');
    return response.json();
  },

  // ============================================
  // File Browser API (for @ file attachments)
  // ============================================

  /**
   * Search files globally for @ attachments.
   *
   * Returns relevance-ranked matches from the user's home subtree.
   */
  async browseFiles(query?: string): Promise<{
    entries: FileEntry[];
    current_path: string;
    parent_path: string | null;
  }> {
    const base = await baseUrl();
    const url = new URL(`${base}/api/files/browse`);
    if (query) {
      url.searchParams.set('query', query);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      const detail = await readErrorDetail(response, 'Failed to browse files');
      throw new Error(detail);
    }
    return response.json();
  },
};
