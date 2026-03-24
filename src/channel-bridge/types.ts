/**
 * Channel Bridge - Shared TypeScript Types
 * 
 * These types define the contracts between the Channel Bridge, Python backend,
 * and Electron main process.
 */

// ============================================================================
// Platform Types
// ============================================================================

export type Platform = 'telegram' | 'discord' | 'whatsapp';

export interface PlatformConfig {
  platform: Platform;
  enabled: boolean;
  credentials: PlatformCredentials;
}

export type PlatformCredentials = 
  | TelegramCredentials 
  | DiscordCredentials 
  | WhatsAppCredentials;

export interface TelegramCredentials {
  botToken: string;
  botUsername?: string;
}

export interface DiscordCredentials {
  botToken: string;
  publicKey: string;
  applicationId: string;
}

export interface WhatsAppCredentials {
  // WhatsApp uses session-based auth, not static credentials
  authMethod: 'pairing_code';
  phoneNumber?: string;
  // If true, forces clearing existing auth state and re-pairing
  forcePairing?: boolean;
}

// ============================================================================
// Configuration
// ============================================================================

export interface ChannelBridgeConfig {
  pythonServerUrl: string;      // e.g., "http://127.0.0.1:8000"
  bridgePort: number;           // e.g., 9000
  platforms: PlatformConfig[];
  userDataDir: string;          // Path to Electron userData for WhatsApp auth
}

// ============================================================================
// Inbound Messages (Platform → Python)
// ============================================================================

export interface InboundMessage {
  platform: Platform;
  senderId: string;
  senderName?: string;
  message: string;
  messageId: string;
  threadId?: string;
  timestamp: number;
  isCommand: boolean;
}

export interface InboundCommand {
  platform: Platform;
  senderId: string;
  senderName?: string;
  command: string;
  args: string[];
  messageId: string;
  timestamp: number;
}

export interface PairingRequest {
  platform: Platform;
  senderId: string;
  displayName: string;
  code: string;
}

// ============================================================================
// Outbound Messages (Python → Platform)
// ============================================================================

export type OutboundMessageType = 'ack' | 'status_update' | 'final_response' | 'error';

export interface OutboundMessage {
  platform: Platform;
  senderId: string;
  message: string;
  messageType: OutboundMessageType;
  replyToMessageId?: string;
}

// ============================================================================
// Python API Responses
// ============================================================================

export interface MessageSubmitResponse {
  success: boolean;
  queued: boolean;
  position?: number;
  itemId?: string;
  error?: string;
}

export interface CommandResponse {
  success: boolean;
  message: string;
  error?: string;
}

export interface PairingResponse {
  success: boolean;
  message: string;
  deviceId?: number;
  error?: string;
}

// ============================================================================
// Platform Status
// ============================================================================

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error';

export interface PlatformStatus {
  platform: Platform;
  status: ConnectionStatus;
  error?: string;
  connectedAt?: number;
  lastMessageAt?: number;
}

// ============================================================================
// Commands
// ============================================================================

export interface CommandDefinition {
  name: string;
  description: string;
  handler: string;
  acceptsArgs: boolean;
}

export const SUPPORTED_COMMANDS: CommandDefinition[] = [
  { name: '/new', description: 'Start a new conversation', handler: 'new_session', acceptsArgs: false },
  { name: '/stop', description: 'Stop the current task', handler: 'stop_current', acceptsArgs: false },
  { name: '/status', description: 'Check current status', handler: 'get_status', acceptsArgs: false },
  { name: '/model', description: 'List or switch models', handler: 'model', acceptsArgs: true },
  { name: '/help', description: 'Show available commands', handler: 'help', acceptsArgs: false },
  { name: '/pair', description: 'Pair with a code', handler: 'pair', acceptsArgs: true },
];

// ============================================================================
// IPC Messages (Channel Bridge ↔ Electron)
// ============================================================================

export interface BridgeReadyMessage {
  type: 'ready';
  port: number;
}

export interface BridgeStatusMessage {
  type: 'status';
  platforms: PlatformStatus[];
}

export interface BridgeErrorMessage {
  type: 'error';
  error: string;
  platform?: Platform;
}

export interface WhatsAppPairingCodeMessage {
  type: 'whatsapp_pairing_code';
  code: string;
}

export type BridgeMessage = 
  | BridgeReadyMessage 
  | BridgeStatusMessage 
  | BridgeErrorMessage
  | WhatsAppPairingCodeMessage;

// ============================================================================
// HTTP API Types
// ============================================================================

export interface SendMessageRequest {
  platform: Platform;
  senderId: string;
  message: string;
  messageType: OutboundMessageType;
  replyToMessageId?: string;
}

export interface RegisterCommandsRequest {
  platform: Platform;
  commands: CommandDefinition[];
}

export interface HealthResponse {
  status: 'ok';
  uptime: number;
  platforms: PlatformStatus[];
}
