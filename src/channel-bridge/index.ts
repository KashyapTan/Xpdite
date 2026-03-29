/**
 * Channel Bridge - Entry Point
 * 
 * A standalone TypeScript service that connects to messaging platforms
 * (Telegram, Discord, WhatsApp) using the Chat SDK and bridges messages 
 * to/from the Python backend.
 * 
 * This service is spawned by Electron alongside the Python server.
 * 
 * Environment variables:
 * - XPDITE_USER_DATA_DIR: Path to Electron's userData directory
 * - PYTHON_SERVER_PORT: Port of the Python server (default: 8000)
 * - BRIDGE_PORT: Port for this service (default: 9000)
 */

/* eslint-disable react-hooks/rules-of-hooks */
// Note: useMultiFileAuthState is from Baileys, NOT a React hook

import type { Adapter, Message } from 'chat';
import * as path from 'path';
import * as fs from 'fs';

import { createBridgeServer } from './server.js';
import { createConfigLoader } from './config/index.js';
import { createCommandHandler } from './commands/index.js';
import { createPythonClient } from './pythonClient.js';
import {
  createWhatsAppOutboundTracker,
  getInboundSenderId,
  getMessageText,
  getMessageTimestampMs,
} from './messageUtils.js';
import type { 
  Platform, 
  PlatformStatus, 
  InboundMessage,
  OutboundMessageType,
  TelegramCredentials,
  DiscordCredentials,
  WhatsAppCredentials,
  BridgeMessage
} from './types.js';

type ChatConstructor = typeof import('chat')['Chat'];
type ChatInstance = InstanceType<ChatConstructor>;
type MemoryStateFactory = typeof import('@chat-adapter/state-memory')['createMemoryState'];
type TelegramAdapterFactory = typeof import('@chat-adapter/telegram')['createTelegramAdapter'];
type DiscordAdapterFactory = typeof import('@chat-adapter/discord')['createDiscordAdapter'];
type BaileysAdapterFactory = typeof import('chat-adapter-baileys')['createBaileysAdapter'];
type ChatSDKTelegramAdapter = ReturnType<TelegramAdapterFactory>;
type ChatSDKDiscordAdapter = ReturnType<DiscordAdapterFactory>;
type ChatSDKBaileysAdapter = ReturnType<BaileysAdapterFactory>;
type BaileysAdapterOptions = Parameters<BaileysAdapterFactory>[0];
type UseMultiFileAuthState = typeof import('baileys')['useMultiFileAuthState'];

let chatSdkCorePromise: Promise<{
  Chat: ChatConstructor;
  createMemoryState: MemoryStateFactory;
}> | null = null;
let telegramAdapterFactoryPromise: Promise<TelegramAdapterFactory> | null = null;
let discordAdapterFactoryPromise: Promise<DiscordAdapterFactory> | null = null;
let whatsAppSdkPromise: Promise<{
  createChatSDKBaileysAdapter: BaileysAdapterFactory;
  useMultiFileAuthState: UseMultiFileAuthState;
}> | null = null;

function loadChatSdkCore() {
  if (!chatSdkCorePromise) {
    chatSdkCorePromise = Promise.all([
      import('chat'),
      import('@chat-adapter/state-memory'),
    ]).then(([chatModule, stateMemoryModule]) => ({
      Chat: chatModule.Chat,
      createMemoryState: stateMemoryModule.createMemoryState,
    }));
  }

  return chatSdkCorePromise;
}

function loadTelegramAdapterFactory() {
  if (!telegramAdapterFactoryPromise) {
    telegramAdapterFactoryPromise = import('@chat-adapter/telegram').then(
      ({ createTelegramAdapter }) => createTelegramAdapter,
    );
  }

  return telegramAdapterFactoryPromise;
}

function loadDiscordAdapterFactory() {
  if (!discordAdapterFactoryPromise) {
    discordAdapterFactoryPromise = import('@chat-adapter/discord').then(
      ({ createDiscordAdapter }) => createDiscordAdapter,
    );
  }

  return discordAdapterFactoryPromise;
}

function loadWhatsAppSdk() {
  if (!whatsAppSdkPromise) {
    whatsAppSdkPromise = Promise.all([
      import('chat-adapter-baileys'),
      import('baileys'),
    ]).then(([baileysAdapterModule, baileysModule]) => ({
      createChatSDKBaileysAdapter: baileysAdapterModule.createBaileysAdapter,
      useMultiFileAuthState: baileysModule.useMultiFileAuthState,
    }));
  }

  return whatsAppSdkPromise;
}

// ============================================================================
// Environment Configuration
// ============================================================================

const userDataDir = process.env.XPDITE_USER_DATA_DIR ?? process.cwd();
const pythonPort = parseInt(process.env.PYTHON_SERVER_PORT ?? '8000', 10);
const bridgePort = parseInt(process.env.BRIDGE_PORT ?? '9000', 10);
const mobileDebugLogs = process.env.XPDITE_MOBILE_DEBUG_LOGS === '1';

// ============================================================================
// Global State
// ============================================================================

interface AdapterState {
  telegram: ChatSDKTelegramAdapter | null;
  discord: ChatSDKDiscordAdapter | null;
  whatsapp: ChatSDKBaileysAdapter | null;
}

const adapters: AdapterState = {
  telegram: null,
  discord: null,
  whatsapp: null,
};

// Current Chat SDK instance
let chatInstance: ChatInstance | null = null;

// Platform connection status tracking
const platformStatuses: Map<Platform, PlatformStatus> = new Map([
  ['telegram', { platform: 'telegram', status: 'disconnected' }],
  ['discord', { platform: 'discord', status: 'disconnected' }],
  ['whatsapp', { platform: 'whatsapp', status: 'disconnected' }],
]);

// Message deduplication - track recently processed message IDs
// Multiple Chat SDK handlers can fire for the same message (onNewMention, onSubscribedMessage, onNewMessage)
const processedMessageIds = new Map<string, number>(); // messageId -> timestamp
const MESSAGE_DEDUP_TTL_MS = 60_000; // Keep message IDs for 60 seconds
const MESSAGE_DEDUP_CLEANUP_INTERVAL_MS = 15_000;
const MESSAGE_STARTUP_GRACE_MS = 30_000;
const WHATSAPP_SELF_HISTORY_GRACE_MS = 5_000;
const MESSAGE_DEDUP_MAX_ENTRIES = 10_000;
let nextDedupCleanupAt = 0;

// Rate limit for "unpaired" response - don't spam users
// Maps sender key (platform:senderId) to last unpaired response timestamp
const lastUnpairedResponse = new Map<string, number>();
const UNPAIRED_RESPONSE_COOLDOWN_MS = 30_000; // Only send "pair first" message once per 30s per user

// WhatsApp can emit our outbound messages back via messages.upsert.
// Track outbound IDs so we can ignore only those echoes.
const whatsappOutboundTracker = createWhatsAppOutboundTracker();

// Track when the bridge started to ignore old messages on reconnect
// Baileys can replay historical messages when reconnecting
let bridgeStartTime = Date.now();
let whatsappConnectionPollInterval: NodeJS.Timeout | null = null;
let whatsappConnectionPollTimeout: NodeJS.Timeout | null = null;

function debugLog(message: string): void {
  if (mobileDebugLogs) {
    console.log(message);
  }
}

function infoLog(message: string): void {
  if (mobileDebugLogs) {
    console.log(message);
  }
}

function errorLog(message: string, ...args: unknown[]): void {
  console.error(message, ...args);
}

function clearWhatsAppConnectionPoller(): void {
  if (whatsappConnectionPollInterval) {
    clearInterval(whatsappConnectionPollInterval);
    whatsappConnectionPollInterval = null;
  }

  if (whatsappConnectionPollTimeout) {
    clearTimeout(whatsappConnectionPollTimeout);
    whatsappConnectionPollTimeout = null;
  }
}

function getDedupKey(platform: Platform, threadId: string, messageId: string): string {
  return `${platform}:${threadId}:${messageId}`;
}

function shouldProcessMessage(
  platform: Platform,
  threadId: string,
  messageId: string,
  messageTimestamp?: number,
): boolean {
  const now = Date.now();
  const dedupKey = getDedupKey(platform, threadId, messageId);

  if (now >= nextDedupCleanupAt) {
    nextDedupCleanupAt = now + MESSAGE_DEDUP_CLEANUP_INTERVAL_MS;

    for (const [id, timestamp] of processedMessageIds) {
      if (now - timestamp > MESSAGE_DEDUP_TTL_MS) {
        processedMessageIds.delete(id);
      }
    }
  }

  while (processedMessageIds.size > MESSAGE_DEDUP_MAX_ENTRIES) {
    const oldest = processedMessageIds.keys().next().value;
    if (!oldest) {
      break;
    }
    processedMessageIds.delete(oldest);
  }
  
  // Check if already processed
  if (processedMessageIds.has(dedupKey)) {
    debugLog(`[ChannelBridge] Skipping duplicate message: ${dedupKey}`);
    return false;
  }
  
  // Ignore messages older than bridge startup (historical messages on reconnect)
  // Keep a small grace window for in-flight messages around startup.
  if (messageTimestamp && messageTimestamp < bridgeStartTime - MESSAGE_STARTUP_GRACE_MS) {
    debugLog(`[ChannelBridge] Skipping old message (${new Date(messageTimestamp).toISOString()}): ${dedupKey}`);
    return false;
  }
  
  // Mark as processed
  processedMessageIds.set(dedupKey, now);

  while (processedMessageIds.size > MESSAGE_DEDUP_MAX_ENTRIES) {
    const oldest = processedMessageIds.keys().next().value;
    if (!oldest) {
      break;
    }
    processedMessageIds.delete(oldest);
  }

  return true;
}

// Reset bridge start time when reconnecting (called from applyConfig)
function resetBridgeStartTime(): void {
  bridgeStartTime = Date.now();
  nextDedupCleanupAt = 0;
  processedMessageIds.clear();
  lastUnpairedResponse.clear();
}

// Check if we should send an "unpaired" response (rate limited)
function shouldSendUnpairedResponse(platform: Platform, senderId: string): boolean {
  const key = `${platform}:${senderId}`;
  const now = Date.now();
  const lastSent = lastUnpairedResponse.get(key);
  
  if (lastSent && now - lastSent < UNPAIRED_RESPONSE_COOLDOWN_MS) {
    debugLog(`[ChannelBridge] Rate limiting unpaired response for ${key}`);
    return false;
  }
  
  lastUnpairedResponse.set(key, now);
  
  // Cleanup old entries periodically
  if (lastUnpairedResponse.size > 1000) {
    for (const [k, ts] of lastUnpairedResponse) {
      if (now - ts > UNPAIRED_RESPONSE_COOLDOWN_MS * 2) {
        lastUnpairedResponse.delete(k);
      }
    }
  }
  
  return true;
}

// ============================================================================
// Helper: Emit structured messages to stdout (read by Electron)
// ============================================================================

function emitMessage(message: BridgeMessage): void {
  // Format: CHANNEL_BRIDGE_MSG <json>
  console.log(`CHANNEL_BRIDGE_MSG ${JSON.stringify(message)}`);
}

function updatePlatformStatus(platform: Platform, update: Partial<PlatformStatus>): void {
  const current = platformStatuses.get(platform) ?? { platform, status: 'disconnected' };
  platformStatuses.set(platform, { ...current, ...update });
}

// ============================================================================
// Main
// ============================================================================

async function main(): Promise<void> {
  infoLog('[ChannelBridge] Starting...');
  debugLog(`[ChannelBridge] User data dir: ${userDataDir}`);
  debugLog(`[ChannelBridge] Python server port: ${pythonPort}`);
  
  // Create Python client
  const pythonClient = createPythonClient(`http://127.0.0.1:${pythonPort}`);
  
  // Create command handler
  const commandHandler = createCommandHandler({
    callPython: (endpoint, body) => pythonClient.post(endpoint, body),
  });

  // Create config loader
  const configLoader = createConfigLoader(userDataDir, pythonPort);

  // Function to get all platform statuses
  function getPlatformStatuses(): PlatformStatus[] {
    return Array.from(platformStatuses.values());
  }

  // Function to send message to a platform
  // Chat SDK's thread.post() is only available from event handlers,
  // so for outbound messages we use the native platform APIs directly.
  async function sendToPlatform(
    platform: Platform,
    senderId: string,
    message: string,
    messageType: OutboundMessageType,
    replyToMessageId?: string,
    threadId?: string,
  ): Promise<string | undefined> {
    debugLog(
      `[ChannelBridge] Sending ${messageType} to ${platform}:${senderId} (thread: ${threadId ?? 'none'}, chars: ${message.length})`,
    );
    // Note: replyToMessageId support is platform-specific and not yet implemented
    if (replyToMessageId) {
      debugLog(`[ChannelBridge] Reply-to message ID: ${replyToMessageId} (not yet implemented)`);
    }
    
    try {
      switch (platform) {
        case 'telegram': {
          const adapter = adapters.telegram;
          if (!adapter) {
            throw new Error('Telegram adapter not initialized');
          }
          const targetThreadId = threadId ?? await adapter.openDM(senderId);
          const sent = await adapter.postMessage(targetThreadId, { markdown: message });
          debugLog(`[ChannelBridge] Telegram message sent to ${senderId} (id: ${sent.id})`);
          return sent.id;
        }
        
        case 'discord': {
          const adapter = adapters.discord;
          if (!adapter) {
            throw new Error('Discord adapter not initialized');
          }
          const targetThreadId = threadId ?? await adapter.openDM(senderId);
          const sent = await adapter.postMessage(targetThreadId, { markdown: message });
          debugLog(`[ChannelBridge] Discord message sent to ${senderId} (id: ${sent.id})`);
          return sent.id;
        }
        
        case 'whatsapp': {
          const adapter = adapters.whatsapp;
          if (!adapter) {
            throw new Error('WhatsApp adapter not initialized');
          }
          const targetThreadId = threadId ?? await adapter.openDM(senderId);
          const sent = await adapter.postMessage(targetThreadId, { markdown: message });
          whatsappOutboundTracker.remember(sent.id, targetThreadId, message);
          debugLog(`[ChannelBridge] WhatsApp message sent to ${senderId} (id: ${sent.id})`);
          return sent.id;
        }
        
        default:
          throw new Error(`Unknown platform: ${platform}`);
      }
    } catch (err) {
      errorLog(`[ChannelBridge] Error sending to ${platform}:`, err);
      throw err;
    }
  }

  // React to a message with an emoji (used for ack instead of text reply)
  async function reactToMessage(
    platform: Platform,
    threadId: string | undefined,
    messageId: string,
    emoji: string,
  ): Promise<void> {
    try {
      const adapter = adapters[platform];
      if (!adapter) return;
      // For DMs, we may need to resolve threadId if not provided
      const resolvedThreadId = threadId ?? (adapter.openDM ? await adapter.openDM(messageId.split(':')[0]) : undefined);
      if (!resolvedThreadId) {
        console.warn(`[ChannelBridge] Cannot react on ${platform}: no threadId and cannot resolve DM`);
        return;
      }
      await adapter.addReaction(resolvedThreadId, messageId, emoji);
      debugLog(`[ChannelBridge] Reacted with ${emoji} on ${platform} message ${messageId}`);
    } catch (err) {
      // Non-fatal — reactions failing should not break the flow
      errorLog(`[ChannelBridge] Failed to react on ${platform} (threadId=${threadId}, msgId=${messageId}):`, err);
    }
  }

  // Show typing indicator on a platform thread
  async function startTypingIndicator(
    platform: Platform,
    threadId: string | undefined,
  ): Promise<void> {
    try {
      const adapter = adapters[platform];
      if (!adapter || !threadId) return;
      await adapter.startTyping(threadId);
    } catch (err) {
      // Non-fatal — typing indicator failing should not break the flow
      errorLog(`[ChannelBridge] Failed to start typing on ${platform} (thread=${threadId}):`, err);
    }
  }

  // Edit an existing message on a platform (used for streaming updates)
  async function editPlatformMessage(
    platform: Platform,
    threadId: string,
    messageId: string,
    content: string,
  ): Promise<void> {
    try {
      const adapter = adapters[platform];
      if (!adapter) {
        throw new Error(`${platform} adapter not initialized`);
      }
      await adapter.editMessage(threadId, messageId, { markdown: content });
      debugLog(`[ChannelBridge] Edited message ${messageId} on ${platform}`);
    } catch (err) {
      errorLog(`[ChannelBridge] Error editing message on ${platform}:`, err);
      throw err;
    }
  }

  // Function to convert Chat SDK message to our InboundMessage format
  function toInboundMessage(
    platform: Platform,
    threadId: string,
    message: Message<unknown>
  ): InboundMessage {
    const text = getMessageText(message);
    const author = message.author as { userId?: string; platformId?: string; userName?: string };
    const authorId = getInboundSenderId(platform, threadId, author);
    const timestamp = getMessageTimestampMs(message) ?? Date.now();
    return {
      platform,
      senderId: authorId,
      senderName: message.author.userName,
      message: text,
      messageId: message.id,
      threadId,
      timestamp,
      isCommand: text.trim().startsWith('/'),
    };
  }

  // Function to handle incoming messages from any platform
  async function handleIncomingMessage(message: InboundMessage): Promise<void> {
    debugLog(
      `[ChannelBridge] Received message from ${message.platform}:${message.senderId} (chars: ${message.message.length}, command: ${message.isCommand})`,
    );

    // Skip empty messages - these are often WhatsApp protocol/sync events
    if (!message.message.trim()) {
      debugLog(`[ChannelBridge] Skipping empty message from ${message.platform}:${message.senderId}`);
      return;
    }

    // Check if this is a command
    if (commandHandler.isCommand(message.message)) {
      infoLog(`[ChannelBridge] Processing command: ${message.message}`);
      const response = await commandHandler.handle(
        message.platform,
        message.senderId,
        message.senderName ?? 'Unknown',
        message.message
      );
      
      if (response) {
        debugLog(`[ChannelBridge] Command response generated (chars: ${response.length})`);
        await sendToPlatform(
          message.platform, 
          message.senderId, 
          response, 
          'final_response', 
          undefined, 
          message.threadId
        );
        return;
      }
    }

    // Not a command, submit to Python
    try {
      const result = await pythonClient.submitMessage(message);
      
      if (result.success && result.queued) {
        // React with thumbs up instead of sending ack message
        await reactToMessage(message.platform, message.threadId, message.messageId, '👍');
        // Show typing indicator while processing
        await startTypingIndicator(message.platform, message.threadId);
        // Only send text if queued behind other messages
        if (result.position && result.position > 1) {
          await sendToPlatform(
            message.platform, 
            message.senderId, 
            `Queued (position ${result.position})`, 
            'ack', 
            undefined, 
            message.threadId
          );
        }
      } else if (!result.success) {
        // Check if it's a pairing error - rate limit these responses
        const isUnpairedError = result.error?.includes('pair first') || result.error?.includes('not paired');
        if (isUnpairedError && !shouldSendUnpairedResponse(message.platform, message.senderId)) {
          debugLog(`[ChannelBridge] Suppressing duplicate unpaired response for ${message.platform}:${message.senderId}`);
          return;
        }
        
        await sendToPlatform(
          message.platform, 
          message.senderId, 
          result.error ?? 'Failed to process message.',
          'final_response',
          undefined,
          message.threadId
        );
      }
    } catch (err) {
      errorLog('[ChannelBridge] Error submitting message:', err);
      
      // Check if it's a pairing issue - rate limit these responses
      const errorMsg = (err as Error).message;
      const isUnpairedError = errorMsg.includes('not paired') || errorMsg.includes('401');
      
      if (isUnpairedError) {
        if (!shouldSendUnpairedResponse(message.platform, message.senderId)) {
          debugLog(`[ChannelBridge] Suppressing duplicate unpaired error response for ${message.platform}:${message.senderId}`);
          return;
        }
        await sendToPlatform(
          message.platform,
          message.senderId,
          'You need to pair first. Send /pair CODE with your Xpdite pairing code.',
          'final_response',
          undefined,
          message.threadId
        );
      } else {
        await sendToPlatform(
          message.platform,
          message.senderId,
          'Failed to connect to Xpdite. Make sure it\'s running.',
          'final_response',
          undefined,
          message.threadId
        );
      }
    }
  }

  function shouldIgnoreInboundMessage(
    platform: Platform,
    threadId: string,
    message: Message<unknown>,
  ): boolean {
    if (!message.author.isMe) {
      return false;
    }

    if (platform !== 'whatsapp') {
      return true;
    }

    const msgTimestamp = getMessageTimestampMs(message);
    if (msgTimestamp && msgTimestamp < bridgeStartTime - WHATSAPP_SELF_HISTORY_GRACE_MS) {
      debugLog(`[ChannelBridge] Ignoring historical WhatsApp self-message: ${message.id}`);
      return true;
    }

    const shouldIgnoreEcho = whatsappOutboundTracker.shouldIgnore(
      message.id,
      threadId,
      getMessageText(message),
    );
    if (shouldIgnoreEcho) {
      debugLog(`[ChannelBridge] Ignoring WhatsApp outbound echo: ${message.id}`);
    }

    return shouldIgnoreEcho;
  }

  async function processInboundChatMessage(
    threadId: string,
    message: Message<unknown>,
    options: {
      subscribeAfter?: boolean;
      thread?: { subscribe: () => Promise<void> };
    } = {},
  ): Promise<void> {
    try {
      const msgTimestamp = getMessageTimestampMs(message);
      const platform = detectPlatform(threadId);
      const msgText = getMessageText(message);

      // Skip empty messages early - these are protocol events (history sync, read receipts, etc.)
      if (!msgText.trim()) {
        debugLog(`[ChannelBridge] Skipping empty ${platform} protocol event id=${message.id}`);
        return;
      }

      if (platform === 'whatsapp') {
        const author = message.author as { userId?: string; platformId?: string; userName?: string; isMe?: boolean };
        const parsedSender = getInboundSenderId(platform, threadId, author);
        debugLog(
          `[ChannelBridge] WhatsApp inbound event id=${message.id} thread=${threadId} isMe=${String(message.author.isMe)} sender=${parsedSender} hasText=${msgText.trim().length > 0} timestamp=${msgTimestamp ?? 'unknown'}`,
        );
      }

      if (!shouldProcessMessage(platform, threadId, message.id, msgTimestamp)) {
        if (platform === 'whatsapp') {
          debugLog(`[ChannelBridge] WhatsApp message skipped by dedup/startup gate id=${message.id}`);
        }
        return;
      }

      if (shouldIgnoreInboundMessage(platform, threadId, message)) {
        if (platform === 'whatsapp') {
          debugLog(`[ChannelBridge] WhatsApp message ignored by self/echo policy id=${message.id}`);
        }
        return;
      }

      const inbound = toInboundMessage(platform, threadId, message);
      if (platform === 'whatsapp') {
        debugLog(
          `[ChannelBridge] WhatsApp inbound normalized id=${inbound.messageId} sender=${inbound.senderId} command=${inbound.isCommand} chars=${inbound.message.length}`,
        );
      }
      updatePlatformStatus(platform, { lastMessageAt: Date.now() });
      await handleIncomingMessage(inbound);

      if (options.subscribeAfter) {
        await options.thread?.subscribe();
      }
    } catch (err) {
      errorLog('[ChannelBridge] Failed processing inbound message:', err);
    }
  }

  // Create HTTP server
  const server = createBridgeServer({
    sendToPlatform,
    startTypingIndicator,
    editPlatformMessage,
    getPlatformStatuses,
  });

  // Start HTTP server
  const actualPort = await server.start(bridgePort);
  
  // Emit ready message (Electron reads this)
  emitMessage({ type: 'ready', port: actualPort });

  // Load config and initialize Chat SDK with adapters
  async function applyConfig(): Promise<void> {
    try {
      // Reset the bridge start time to ignore old messages from reconnection
      resetBridgeStartTime();
      clearWhatsAppConnectionPoller();
      
      const config = await configLoader.load();
      pythonClient.setBaseUrl(config.pythonServerUrl);
      
      // CRITICAL: Clean up existing Chat instance and adapters FIRST
      // This prevents polling conflicts and WebSocket issues during reload
      if (chatInstance) {
        debugLog('[ChannelBridge] Cleaning up existing Chat instance before reload...');
        // Chat SDK doesn't have a built-in destroy() method, but we can disconnect adapters
      }
      
      // Disconnect all existing adapters before recreating.
      // IMPORTANT: Skip WhatsApp teardown if it's already connected and the
      // new config doesn't request re-pairing. This prevents the race condition
      // where the forcePairing reset (triggered by our own connection notification)
      // causes a config reload that tears down a perfectly working connection.
      const newWhatsappConfig = config.platforms.find(p => p.platform === 'whatsapp');
      const whatsappAlreadyConnected = adapters.whatsapp?.botUserId;
      const newForcePairing = (newWhatsappConfig?.credentials as WhatsAppCredentials | undefined)?.forcePairing;
      const shouldKeepWhatsApp = whatsappAlreadyConnected && newWhatsappConfig?.enabled && !newForcePairing;

      if (adapters.whatsapp && !shouldKeepWhatsApp) {
        debugLog('[ChannelBridge] Disconnecting existing WhatsApp adapter...');
        try {
          await adapters.whatsapp.disconnect?.();
        } catch (err) {
          debugLog(`[ChannelBridge] Error disconnecting WhatsApp: ${(err as Error).message}`);
        }
        adapters.whatsapp = null;
      } else if (shouldKeepWhatsApp) {
        debugLog('[ChannelBridge] Keeping existing WhatsApp connection (already connected, no re-pairing needed)');
      }
      
      if (adapters.telegram) {
        debugLog('[ChannelBridge] Stopping existing Telegram adapter...');
        try {
          // Telegram adapter uses polling, calling stopPolling if available
          const tgAdapter = adapters.telegram as unknown as { stopPolling?: () => void };
          tgAdapter.stopPolling?.();
        } catch (err) {
          debugLog(`[ChannelBridge] Error stopping Telegram polling: ${(err as Error).message}`);
        }
        adapters.telegram = null;
      }
      
      if (adapters.discord) {
        debugLog('[ChannelBridge] Disconnecting existing Discord adapter...');
        adapters.discord = null;
      }
      
      // Clear the chat instance
      chatInstance = null;
      
      // Small delay to allow connections to fully close
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Build adapters object for Chat SDK
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const chatAdapters: Record<string, Adapter<any, any>> = {};
      
      // Initialize Telegram if configured
      const telegramConfig = config.platforms.find(p => p.platform === 'telegram');
      const telegramCredentials = telegramConfig?.enabled
        ? telegramConfig.credentials as TelegramCredentials
        : null;
      const telegramAdapterFactoryLoad =
        telegramConfig?.enabled && telegramCredentials?.botToken
          ? loadTelegramAdapterFactory()
          : Promise.resolve(null);
      
      if (telegramConfig?.enabled) {
        const creds = telegramCredentials;
        debugLog('[ChannelBridge] Initializing Telegram adapter (Chat SDK)...');
        
        updatePlatformStatus('telegram', { status: 'connecting' });
        
        try {
          if (!creds?.botToken) {
            throw new Error('Telegram bot token is required');
          }

          const createTelegramAdapter = await telegramAdapterFactoryLoad;
          if (!createTelegramAdapter) {
            throw new Error('Telegram adapter loader unavailable');
          }

          adapters.telegram = createTelegramAdapter({
            botToken: creds.botToken,
            userName: creds.botUsername,
            mode: 'polling', // Desktop app uses polling, not webhooks
            longPolling: {
              timeout: 30,
              dropPendingUpdates: false,
            },
          });
          
          chatAdapters.telegram = adapters.telegram;
          updatePlatformStatus('telegram', { status: 'connected', connectedAt: Date.now(), error: undefined });
          debugLog('[ChannelBridge] Telegram adapter initialized');
        } catch (err) {
          errorLog('[ChannelBridge] Failed to initialize Telegram:', err);
          updatePlatformStatus('telegram', { status: 'error', error: (err as Error).message });
        }
      } else {
        // Telegram is disabled - just update status (adapter already disconnected at top)
        updatePlatformStatus('telegram', { status: 'disconnected', connectedAt: undefined });
      }
      
      // Initialize Discord if configured
      const discordConfig = config.platforms.find(p => p.platform === 'discord');
      const discordCredentials = discordConfig?.enabled
        ? discordConfig.credentials as DiscordCredentials
        : null;
      const discordAdapterFactoryLoad =
        discordConfig?.enabled
        && discordCredentials?.botToken
        && discordCredentials?.publicKey
        && discordCredentials?.applicationId
          ? loadDiscordAdapterFactory()
          : Promise.resolve(null);
      
      if (discordConfig?.enabled) {
        const creds = discordCredentials;
        debugLog('[ChannelBridge] Initializing Discord adapter (Chat SDK)...');
        
        updatePlatformStatus('discord', { status: 'connecting' });
        
        try {
          if (!creds?.botToken) {
            throw new Error('Discord bot token is required');
          }
          if (!creds.publicKey) {
            throw new Error('Discord public key is required');
          }
          if (!creds.applicationId) {
            throw new Error('Discord application ID is required');
          }

          const createDiscordAdapter = await discordAdapterFactoryLoad;
          if (!createDiscordAdapter) {
            throw new Error('Discord adapter loader unavailable');
          }

          adapters.discord = createDiscordAdapter({
            botToken: creds.botToken,
            publicKey: creds.publicKey,
            applicationId: creds.applicationId,
          });
          
          chatAdapters.discord = adapters.discord;
          updatePlatformStatus('discord', { status: 'connected', connectedAt: Date.now(), error: undefined });
          debugLog('[ChannelBridge] Discord adapter initialized');
        } catch (err) {
          errorLog('[ChannelBridge] Failed to initialize Discord:', err);
          updatePlatformStatus('discord', { status: 'error', error: (err as Error).message });
        }
      } else {
        // Discord is disabled - just update status (adapter already disconnected at top)
        updatePlatformStatus('discord', { status: 'disconnected', connectedAt: undefined });
      }
      
      // Initialize WhatsApp if configured
      const whatsappConfig = newWhatsappConfig;
      const whatsappCredentials = whatsappConfig?.enabled
        ? whatsappConfig.credentials as WhatsAppCredentials
        : null;
      let whatsappNeedsPairing = false;
      const whatsAppSdkLoad =
        whatsappConfig?.enabled && !shouldKeepWhatsApp && !!whatsappCredentials?.phoneNumber
          ? loadWhatsAppSdk()
          : Promise.resolve(null);
      
      // If we kept the existing WhatsApp adapter, just reuse it
      if (shouldKeepWhatsApp && adapters.whatsapp) {
        debugLog('[ChannelBridge] Reusing existing WhatsApp adapter (skipping teardown/rebuild)');
        chatAdapters.whatsapp = adapters.whatsapp;
        updatePlatformStatus('whatsapp', { status: 'connected' });
      } else if (whatsappConfig?.enabled) {
        const creds = whatsappCredentials;
        debugLog('[ChannelBridge] Initializing WhatsApp adapter (Chat SDK Baileys)...');
        
        updatePlatformStatus('whatsapp', { status: 'connecting' });
        
        try {
          if (!creds?.phoneNumber) {
            throw new Error('WhatsApp phone number is required for pairing code authentication');
          }

          const whatsAppSdk = await whatsAppSdkLoad;
          if (!whatsAppSdk) {
            throw new Error('WhatsApp SDK loader unavailable');
          }

          const {
            createChatSDKBaileysAdapter,
            useMultiFileAuthState,
          } = whatsAppSdk;

          // Load or create WhatsApp auth state
          const authDir = path.join(userDataDir, 'whatsapp_auth');

          const formattedPhone = creds.phoneNumber.replace(/\D/g, '');
          if (!formattedPhone) {
            throw new Error('WhatsApp phone number is invalid');
          }
          
          // Clear auth state if:
          // 1. creds.json doesn't exist (fresh install)
          // 2. forcePairing is true (user requested re-pairing)
          const credsPath = path.join(authDir, 'creds.json');
          const needsCleanState = !fs.existsSync(credsPath) || creds.forcePairing;
          
          if (needsCleanState) {
            debugLog(`[ChannelBridge] Clearing WhatsApp auth state (${creds.forcePairing ? 'forcePairing requested' : 'fresh pairing'})`);
            // Clean all auth files for a fresh start
            if (fs.existsSync(authDir)) {
              const files = fs.readdirSync(authDir);
              for (const file of files) {
                try {
                  fs.unlinkSync(path.join(authDir, file));
                } catch {
                  // Ignore errors
                }
              }
            }
          }
          
          const { state, saveCreds } = await useMultiFileAuthState(authDir);
          const isRegistered = Boolean((state as { creds?: { registered?: boolean } }).creds?.registered);
          whatsappNeedsPairing = !isRegistered;
          debugLog(`[ChannelBridge] WhatsApp auth state: registered=${isRegistered}, needsPairing=${whatsappNeedsPairing}, credsExist=${fs.existsSync(path.join(authDir, 'creds.json'))}`);
          
          // Track if we've already requested a pairing code for this session
          let pairingCodeRequested = false;
          
          // Build adapter options.
          // NOTE: Do NOT use phoneNumber/onPairingCode — the adapter's built-in
          // flow calls requestPairingCode on connection === "connecting" which is
          // BEFORE the WebSocket is actually open, causing a 428 "Connection Closed"
          // error. Additionally, the adapter resets its internal guard flag on
          // reconnect, leading to infinite retry loops that result in a 401 logout.
          // Instead, use onQR as the trigger since QR emission means the WS socket
          // is fully open and ready for protocol operations.
          const baileysOptions: BaileysAdapterOptions = {
            auth: { state, saveCreds },
            userName: 'xpdite-bot',
            // Prevent Baileys from printing QR codes to stdout (conflicts
            // with Electron's structured stdout parsing).
            socketOptions: {
              printQRInTerminal: false,
              // Skip history sync to prevent event buffering that causes
              // pre-key upload timeouts and broken connections on reconnect.
              // Xpdite doesn't need message history from WhatsApp.
              shouldSyncHistoryMessage: () => false,
              markOnlineOnConnect: false,
              // getMessage is required by Baileys for E2E decryption retries.
              // Without it, messages that fail to decrypt are silently dropped.
              getMessage: async () => undefined,
            },
            // Use onQR as the trigger to request pairing code.
            // QR generation only happens when the socket needs fresh auth and
            // the WebSocket is fully open — the correct time for requestPairingCode.
            onQR: whatsappNeedsPairing ? async () => {
              if (pairingCodeRequested) return; // Only request once per applyConfig cycle
              pairingCodeRequested = true;
              
              debugLog('[ChannelBridge] WhatsApp QR event received, requesting pairing code...');
              try {
                // Small delay to ensure the socket is fully stabilized after QR generation.
                await new Promise(resolve => setTimeout(resolve, 500));

                // Access the internal socket to call requestPairingCode.
                // The adapter's _socket field holds the live Baileys WASocket.
                const internal = adapters.whatsapp as unknown as { 
                  _socket?: { requestPairingCode: (phone: string) => Promise<string> } 
                };
                if (internal._socket?.requestPairingCode) {
                  const code = await internal._socket.requestPairingCode(formattedPhone);
                  debugLog('[ChannelBridge] ✓ WhatsApp pairing code received');
                  emitMessage({ type: 'whatsapp_pairing_code', code });
                } else {
                  errorLog('[ChannelBridge] Cannot access WhatsApp socket for pairing code');
                }
              } catch (err) {
                errorLog('[ChannelBridge] Failed to request pairing code:', err);
                updatePlatformStatus('whatsapp', { 
                  status: 'error', 
                  error: `Failed to request pairing code: ${(err as Error).message}` 
                });
              }
            } : undefined,
          };

          debugLog(`[ChannelBridge] WhatsApp ${whatsappNeedsPairing ? 'needs pairing' : 'already registered'}, phone: ${formattedPhone.substring(0, 4)}****`);
          
          adapters.whatsapp = createChatSDKBaileysAdapter(baileysOptions);
          chatAdapters.whatsapp = adapters.whatsapp;
          
          // NOTE: Do NOT call connect() here!
          // WhatsApp connect() must be called AFTER chatInstance.initialize()
          // per the Chat SDK documentation.
          
          updatePlatformStatus('whatsapp', { status: 'connecting' });
          debugLog('[ChannelBridge] WhatsApp adapter created (will connect after Chat init)');
        } catch (err) {
          errorLog('[ChannelBridge] Failed to initialize WhatsApp:', err);
          updatePlatformStatus('whatsapp', { status: 'error', error: (err as Error).message });
        }
      } else if (!shouldKeepWhatsApp) {
        // WhatsApp is disabled - just update status (adapter already disconnected at top)
        updatePlatformStatus('whatsapp', { status: 'disconnected', connectedAt: undefined });
      }
      
      // Create or recreate the Chat instance with current adapters
      if (Object.keys(chatAdapters).length > 0) {
        const { Chat, createMemoryState } = await loadChatSdkCore();
        chatInstance = new Chat({
          userName: 'xpdite-bot',
          adapters: chatAdapters,
          state: createMemoryState(),
        });
        
        // Register message handlers
        // onNewMention: fires when bot is @-mentioned in a group it hasn't subscribed to
        chatInstance.onNewMention(async (thread, message) => {
          debugLog(`[ChannelBridge] 📨 onNewMention fired: thread=${thread.id} msgId=${message.id} author=${message.author.userName} isMe=${message.author.isMe}`);
          await processInboundChatMessage(thread.id, message, {
            subscribeAfter: true,
            thread,
          });
        });
        
        // onSubscribedMessage: fires for every message in a subscribed thread
        chatInstance.onSubscribedMessage(async (thread, message) => {
          debugLog(`[ChannelBridge] 📨 onSubscribedMessage fired: thread=${thread.id} msgId=${message.id} author=${message.author.userName} isMe=${message.author.isMe}`);
          await processInboundChatMessage(thread.id, message);
        });

        // onNewMessage: fires for any message matching pattern in unsubscribed thread
        // We use this to handle DMs
        chatInstance.onNewMessage(/.*/, async (thread, message) => {
          debugLog(`[ChannelBridge] 📨 onNewMessage fired: thread=${thread.id} msgId=${message.id} author=${message.author.userName} isMe=${message.author.isMe}`);
          await processInboundChatMessage(thread.id, message);
        });
        
        // Initialize the Chat instance (attaches adapters, starts Telegram/Discord)
        await chatInstance.initialize();
        debugLog('[ChannelBridge] Chat SDK instance initialized');
        
        // NOW connect WhatsApp - must be AFTER initialize() per Chat SDK docs
        // WhatsApp is WebSocket-based and needs to connect after Chat is initialized.
        // The onQR callback will fire during connection if fresh pairing is needed,
        // which triggers our requestPairingCode logic.
        // IMPORTANT: Skip connect() for reused adapters — calling connect() on an
        // already-connected adapter creates a second socket, causing an infinite loop.
        if (adapters.whatsapp && !shouldKeepWhatsApp) {
          try {
            debugLog('[ChannelBridge] Connecting WhatsApp WebSocket...');
            
            await adapters.whatsapp.connect();
            
            // Hook into the Baileys socket directly to log raw events.
            // This bypasses the Chat SDK to help diagnose if messages.upsert
            // events are arriving from Baileys at all.
            const waInternal = adapters.whatsapp as unknown as {
              _socket?: { ev: { on: (event: string, handler: (...args: unknown[]) => void) => void } }
            };
            if (waInternal._socket?.ev) {
              waInternal._socket.ev.on('messages.upsert', (...args: unknown[]) => {
                const data = args[0] as { messages?: unknown[]; type?: string };
                debugLog(`[ChannelBridge] 🔔 RAW messages.upsert: type=${data?.type} count=${data?.messages?.length}`);
              });
              waInternal._socket.ev.on('connection.update', (...args: unknown[]) => {
                const data = args[0] as { connection?: string; lastDisconnect?: unknown };
                debugLog(`[ChannelBridge] 🔔 RAW connection.update: connection=${data?.connection}`);
              });
              debugLog('[ChannelBridge] ✓ Direct Baileys event listeners attached');
            }

            // Check if we're already connected (happens when resuming an existing session)
            if (adapters.whatsapp.botUserId) {
              infoLog(`[ChannelBridge] WhatsApp connected as ${adapters.whatsapp.botUserId}`);
              updatePlatformStatus('whatsapp', { status: 'connected', connectedAt: Date.now(), error: undefined });
              
              // Notify Python to reset forcePairing flag
              pythonClient.post('/internal/mobile/whatsapp/connection', {
                status: 'connected',
                bot_user_id: adapters.whatsapp.botUserId,
              }).catch(err => errorLog('[ChannelBridge] Failed to notify Python of WhatsApp connection:', err));
            } else {
              // For pairing-code auth, we stay in connecting until the linked-device
              // flow is completed on the phone.
              debugLog('[ChannelBridge] WhatsApp connect() completed - waiting for pairing...');
              updatePlatformStatus('whatsapp', { status: 'connecting', error: undefined });
              
              // Start polling for connection status (pairing completion)
              clearWhatsAppConnectionPoller();
              whatsappConnectionPollInterval = setInterval(() => {
                if (adapters.whatsapp?.botUserId) {
                  infoLog(`[ChannelBridge] WhatsApp paired successfully as ${adapters.whatsapp.botUserId}`);
                  updatePlatformStatus('whatsapp', { status: 'connected', connectedAt: Date.now(), error: undefined });
                  emitMessage({ type: 'status', platforms: getPlatformStatuses() });
                  clearWhatsAppConnectionPoller();
                  
                  // Notify Python to reset forcePairing flag
                  pythonClient.post('/internal/mobile/whatsapp/connection', {
                    status: 'connected',
                    bot_user_id: adapters.whatsapp.botUserId,
                  }).catch(err => errorLog('[ChannelBridge] Failed to notify Python of WhatsApp connection:', err));
                }
              }, 1000);
              
              // Stop checking after 5 minutes (pairing timeout)
              whatsappConnectionPollTimeout = setTimeout(() => {
                clearWhatsAppConnectionPoller();
              }, 5 * 60 * 1000);
            }
          } catch (err) {
            errorLog('[ChannelBridge] WhatsApp connection failed:', err);
            updatePlatformStatus('whatsapp', { status: 'error', error: (err as Error).message });
          }
        }
      } else {
        chatInstance = null;
        debugLog('[ChannelBridge] No adapters configured, Chat SDK instance not created');
      }
      
      // Emit status update
      emitMessage({ type: 'status', platforms: getPlatformStatuses() });
      
    } catch (err) {
      errorLog('[ChannelBridge] Error applying config:', err);
      emitMessage({ type: 'error', error: (err as Error).message });
    }
  }

  // Helper to detect platform from thread ID
  // Chat SDK prefixes thread IDs with adapter name
  function detectPlatform(threadId: string): Platform {
    if (threadId.startsWith('telegram:') || threadId.includes('telegram')) {
      return 'telegram';
    } else if (threadId.startsWith('discord:') || threadId.includes('discord')) {
      return 'discord';
    } else if (threadId.startsWith('baileys:') || threadId.startsWith('whatsapp:') || threadId.includes('@s.whatsapp')) {
      return 'whatsapp';
    }
    // Default to telegram if unknown
    return 'telegram';
  }

  // Initial config load
  await applyConfig();

  // Watch for config changes
  configLoader.startWatching(async () => {
    infoLog('[ChannelBridge] Config changed, reloading...');
    await applyConfig();
  });

  // Handle shutdown signals
  async function shutdown(): Promise<void> {
    infoLog('[ChannelBridge] Shutting down...');
    
    configLoader.stopWatching();
    clearWhatsAppConnectionPoller();
    
    // Disconnect WhatsApp (needs explicit cleanup)
    if (adapters.whatsapp) {
      await adapters.whatsapp.disconnect?.();
    }
    
    // Telegram and Discord don't need explicit cleanup when using Chat SDK
    // The Chat SDK handles adapter cleanup
    
    await server.stop();
    
    process.exit(0);
  }

  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);

  infoLog(`[ChannelBridge] Ready on port ${actualPort}`);
}

// Handle unhandled rejections (important for async callbacks like pairing code)
process.on('unhandledRejection', (reason, promise) => {
  errorLog('[ChannelBridge] Unhandled Rejection at:', promise, 'reason:', reason);
  emitMessage({ type: 'error', error: 'Internal bridge error. Check logs for details.' });
});

process.on('uncaughtException', (err) => {
  errorLog('[ChannelBridge] Uncaught Exception:', err);
  emitMessage({ type: 'error', error: 'Bridge process crashed with an internal error.' });
});

// Run
main().catch((err) => {
  errorLog('[ChannelBridge] Fatal error:', err);
  emitMessage({ type: 'error', error: (err as Error).message });
  process.exit(1);
});
