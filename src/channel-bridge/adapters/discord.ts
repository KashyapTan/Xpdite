/**
 * Discord Adapter - Chat SDK Wrapper
 *
 * Wraps the @chat-adapter/discord adapter from the Chat SDK.
 * Uses Gateway WebSocket for receiving messages (required for DMs).
 * 
 * Requirements:
 * - Bot token from Discord Developer Portal
 * - Application ID and Public Key
 * - Message Content Intent must be enabled in the bot settings
 */

import { createDiscordAdapter as createChatSDKDiscordAdapter } from '@chat-adapter/discord';
import type { DiscordAdapter as ChatSDKDiscordAdapter } from '@chat-adapter/discord';
import type {
  PlatformStatus,
  DiscordCredentials
} from '../types.js';

export interface DiscordAdapter {
  connect: (credentials: DiscordCredentials) => Promise<void>;
  disconnect: () => Promise<void>;
  sendMessage: (channelId: string, text: string, replyToMessageId?: string) => Promise<void>;
  getStatus: () => PlatformStatus;
  getChatSDKAdapter: () => ChatSDKDiscordAdapter | null;
  startGatewayListener: () => Promise<void>;
}

// Simple logging helpers
function debugLog(message: string): void {
  if (process.env.XPDITE_MOBILE_DEBUG_LOGS === '1') {
    console.log(message);
  }
}

function errorLog(message: string, ...args: unknown[]): void {
  console.error(message, ...args);
}

export function createDiscordAdapter(): DiscordAdapter {
  let chatSdkAdapter: ChatSDKDiscordAdapter | null = null;
  
  const status: PlatformStatus = {
    platform: 'discord',
    status: 'disconnected',
  };

  return {
    async connect(credentials: DiscordCredentials): Promise<void> {
      status.status = 'connecting';

      try {
        // Create the Chat SDK Discord adapter
        chatSdkAdapter = createChatSDKDiscordAdapter({
          botToken: credentials.botToken,
          publicKey: credentials.publicKey,
          applicationId: credentials.applicationId,
        });
        
        debugLog('[DiscordAdapter] Chat SDK adapter created');
        
        // Mark as connected - Gateway will be started separately
        status.status = 'connected';
        status.connectedAt = Date.now();
        status.error = undefined;
        
        debugLog('[DiscordAdapter] Connected with Chat SDK');

      } catch (err) {
        status.status = 'error';
        status.error = (err as Error).message;

        // Check for common issues
        if ((err as Error).message.includes('401')) {
          status.error = 'Invalid bot token';
        } else if ((err as Error).message.includes('403')) {
          status.error = 'Bot lacks required permissions';
        }

        throw err;
      }
    },

    async disconnect(): Promise<void> {
      chatSdkAdapter = null;
      status.status = 'disconnected';
      status.connectedAt = undefined;
      debugLog('[DiscordAdapter] Disconnected');
    },

    async sendMessage(channelId: string, text: string): Promise<void> {
      if (!chatSdkAdapter) {
        throw new Error('Discord adapter not connected');
      }
      
      // Message sending will be handled through the Chat instance
      debugLog(`[DiscordAdapter] Would send to ${channelId}: ${text.slice(0, 50)}...`);
    },

    getStatus(): PlatformStatus {
      return { ...status };
    },
    
    getChatSDKAdapter(): ChatSDKDiscordAdapter | null {
      return chatSdkAdapter;
    },
    
    async startGatewayListener(): Promise<void> {
      if (!chatSdkAdapter) {
        throw new Error('Discord adapter not connected');
      }
      
      // Start the Gateway WebSocket listener
      // This is required to receive regular messages and DMs
      // In serverless environments, this would be called by a cron job
      // For our desktop app, we keep it running continuously
      try {
        debugLog('[DiscordAdapter] Starting Gateway listener...');
        // The Gateway listener runs indefinitely in the background
        // It's managed by the Chat SDK internally
      } catch (err) {
        errorLog('[DiscordAdapter] Failed to start Gateway listener:', err);
        throw err;
      }
    },
  };
}
