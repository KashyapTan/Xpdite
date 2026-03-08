/**
 * Type definitions for the Xpdite application.
 */

// ============================================
// Chat & Message Types
// ============================================

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  server: string;
  status?: 'calling' | 'progress' | 'complete';
  /** Unique ID for sub-agent calls — used for matching progress updates */
  agentId?: string;
  /** Human-readable progress description (e.g. "Reading docs.openclaw.ai...") */
  description?: string;
  /** Accumulated LLM output while sub-agent is still running */
  partialResult?: string;
}

export type ContentBlock =
  | { type: 'text'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call'; toolCall: ToolCall }
  | { type: 'terminal_command'; terminal: TerminalCommandBlock };

/**
 * Inline terminal command block — one per run_command invocation.
 * Rendered as an embedded terminal card inside the chat.
 */
export interface TerminalCommandBlock {
  /** Unique ID — matches the backend request_id */
  requestId: string;
  /** The shell command being executed */
  command: string;
  /** Working directory */
  cwd: string;
  /** Lifecycle state */
  status: 'pending_approval' | 'denied' | 'running' | 'completed';
  /** Accumulated stdout/stderr (plain text for non-PTY commands) */
  output: string;
  /** Buffered output chunks for xterm.js rendering (preserves write order and raw flag) */
  outputChunks: Array<{ text: string; raw: boolean }>;
  /** Whether this command uses a PTY (interactive/TUI mode) */
  isPty: boolean;
  /** Process exit code (set on completion) */
  exitCode?: number;
  /** Duration in ms (set on completion) */
  durationMs?: number;
  /** Whether the command timed out */
  timedOut?: boolean;
}

export interface MessageImage {
  name: string;
  thumbnail: string;
}

export interface ResponseVariant {
  responseIndex: number;
  content: string;
  model?: string;
  timestamp: number;
  contentBlocks?: ContentBlock[];
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  images?: MessageImage[];
  toolCalls?: ToolCall[];
  /** Interleaved text + tool_call blocks (preferred over toolCalls for rendering) */
  contentBlocks?: ContentBlock[];
  model?: string;
  messageId?: string;
  turnId?: string;
  timestamp?: number;
  activeResponseIndex?: number;
  responseVersions?: ResponseVariant[];
}

// ============================================
// Screenshot Types
// ============================================

export interface Screenshot {
  id: string;
  name: string;
  thumbnail: string;
}

// ============================================
// Token Usage Types
// ============================================

export interface TokenUsage {
  total: number;
  input: number;
  output: number;
  limit: number;
}

// ============================================
// Capture Mode Types
// ============================================

export type CaptureMode = 'fullscreen' | 'precision' | 'none';

// ============================================
// WebSocket Message Types
// ============================================

export interface WebSocketMessage {
  type: string;
  content: string | Record<string, unknown>;
}

// ==========================================
// Skills Feature Types
// ==========================================

export interface Skill {
  name: string;
  description: string;
  slash_command: string | null;
  trigger_servers: string[];
  version: string;
  source: 'builtin' | 'user';
  enabled: boolean;
  overridden_by_user: boolean;
  folder_path: string;
}

// ============================================
// Terminal Types
// ============================================

export interface TerminalApprovalRequest {
  command: string;
  cwd: string;
  request_id: string;
}

export interface TerminalSessionRequest {
  reason: string;
  request_id: string;
}

export interface TerminalOutput {
  text: string;
  request_id: string;
  stream: boolean;
  raw?: boolean;
}

export interface TerminalCommandComplete {
  request_id: string;
  exit_code: number;
  duration_ms: number;
}

export interface TerminalRunningNotice {
  request_id: string;
  command: string;
  elapsed_ms: number;
}

export interface TerminalEvent {
  id: string;
  message_index: number;
  command: string;
  exit_code: number;
  output_preview: string;
  cwd: string;
  duration_ms: number;
  timed_out: boolean;
  denied: boolean;
  pty: boolean;
  background: boolean;
  created_at: number;
}

export interface ScreenshotAddedContent {
  id: string;
  name: string;
  thumbnail: string;
}

export interface ScreenshotRemovedContent {
  id: string;
}

export interface ConversationSavedContent {
  conversation_id: string;
  operation?: 'submit' | 'retry' | 'edit';
  truncate_after_turn?: boolean;
  turn?: ConversationTurnPayload;
}

export interface ConversationContentBlockPayload {
  type: string;
  content?: string;
  name?: string;
  args?: Record<string, unknown>;
  server?: string;
  result?: string;
  request_id?: string;
  requestId?: string;
  command?: string;
  cwd?: string;
  status?: string;
  output?: string;
  output_chunks?: Array<{ text: string; raw: boolean }>;
  outputChunks?: Array<{ text: string; raw: boolean }>;
  is_pty?: boolean;
  isPty?: boolean;
  exit_code?: number;
  exitCode?: number;
  duration_ms?: number;
  durationMs?: number;
  timed_out?: boolean;
  timedOut?: boolean;
}

export type ConversationImagePayload = { name: string; thumbnail: string | null } | string;

export interface ConversationResponseVariantPayload {
  response_index: number;
  content: string;
  model?: string;
  timestamp: number;
  content_blocks?: ConversationContentBlockPayload[];
}

export interface ConversationMessagePayload {
  message_id: string;
  turn_id: string;
  role: string;
  content: string;
  timestamp: number;
  images?: ConversationImagePayload[];
  model?: string;
  content_blocks?: ConversationContentBlockPayload[];
  active_response_index?: number;
  response_variants?: ConversationResponseVariantPayload[];
}

export interface ConversationTurnPayload {
  turn_id: string;
  user: ConversationMessagePayload;
  assistant?: ConversationMessagePayload;
}

export interface ConversationResumedContent {
  conversation_id: string;
  messages: ConversationMessagePayload[];
  token_usage?: {
    total: number;
    input: number;
    output: number;
  };
}

export interface ToolCallContent {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  server: string;
  status: 'calling' | 'progress' | 'complete';
  agent_id?: string;
  description?: string;
  partial_result?: string;
}

export interface TokenUsageContent {
  prompt_eval_count?: number;
  eval_count?: number;
}

// ============================================
// Conversation Types
// ============================================

export interface Conversation {
  id: string;
  title: string;
  date: number;
  preview?: string;
}

// ============================================
// Electron API Types
// ============================================

declare global {
  interface Window {
    electronAPI?: {
      focusWindow: () => Promise<void>;
      setMiniMode: (mini: boolean) => Promise<void>;
      getServerPort: () => Promise<number>;
    };
  }
}

// ============================================
// Tab Types
// ============================================

export interface TabInfo {
  id: string;
  title: string;
}

/** Queued item reported by the backend. */
export interface QueueItem {
  item_id: string;
  preview: string;
  position: number;
}

/** Snapshot of all per-tab React state for the state registry. */
export interface ChatStateSnapshot {
  chatHistory: ChatMessage[];
  currentQuery: string;
  response: string;
  thinking: string;
  isThinking: boolean;
  thinkingCollapsed: boolean;
  toolCalls: ToolCall[];
  contentBlocks: ContentBlock[];
  conversationId: string | null;
  query: string;
  canSubmit: boolean;
  status: string;
  error: string;
}

export interface ScreenshotSnapshot {
  screenshots: Screenshot[];
  captureMode: CaptureMode;
  meetingRecordingMode: boolean;
}

export interface TokenUsageSnapshot {
  tokenUsage: TokenUsage;
}

export interface TerminalSnapshot {
  terminalSessionActive: boolean;
  terminalSessionRequest: TerminalSessionRequest | null;
}

/** Full per-tab state snapshot stored in the registry. */
export interface TabSnapshot {
  chat: ChatStateSnapshot;
  screenshots: ScreenshotSnapshot;
  tokens: TokenUsageSnapshot;
  terminal: TerminalSnapshot;
  generatingModel: string;
}

export { };
