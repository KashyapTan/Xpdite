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
  status?: 'calling' | 'complete';
}

export type ContentBlock =
  | { type: 'text'; content: string }
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
  /** Accumulated stdout/stderr lines */
  output: string;
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

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinking?: string;
  images?: MessageImage[];
  toolCalls?: ToolCall[];
  /** Interleaved text + tool_call blocks (preferred over toolCalls for rendering) */
  contentBlocks?: ContentBlock[];
  model?: string;
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
  id: number;
  skill_name: string;
  display_name: string;
  slash_command: string;
  content: string;
  is_default: boolean;
  is_modified: boolean;
  enabled: boolean;
  created_at: number;
  updated_at: number;
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
}

export interface ConversationResumedContent {
  conversation_id: string;
  messages: Array<{
    role: string;
    content: string;
    images?: Array<{ name: string; thumbnail: string }>;
    model?: string;
    content_blocks?: Array<{
      type: string;
      content?: string;
      name?: string;
      args?: Record<string, unknown>;
      server?: string;
    }>;
  }>;
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
  status: 'calling' | 'complete';
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
    };
  }
}

export { };
