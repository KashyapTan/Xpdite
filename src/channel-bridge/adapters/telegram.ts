/**
 * Telegram Adapter - Chat SDK Wrapper
 * 
 * Wraps the @chat-adapter/telegram adapter from the Chat SDK.
 * Uses polling mode for desktop app (no webhook needed).
 */

import { createTelegramAdapter as createChatSDKTelegramAdapter } from '@chat-adapter/telegram';
import type { TelegramAdapter as ChatSDKTelegramAdapter } from '@chat-adapter/telegram';
import type { 
  PlatformStatus, 
  TelegramCredentials,
} from '../types.js';

export interface TelegramAdapter {
  connect: (credentials: TelegramCredentials) => Promise<void>;
  disconnect: () => Promise<void>;
  sendMessage: (chatId: string, text: string, replyToMessageId?: string) => Promise<void>;
  getStatus: () => PlatformStatus;
  getChatSDKAdapter: () => ChatSDKTelegramAdapter | null;
}

export function createTelegramAdapter(): TelegramAdapter {
  let chatSdkAdapter: ChatSDKTelegramAdapter | null = null;
  
  const status: PlatformStatus = {
    platform: 'telegram',
    status: 'disconnected',
  };

  return {
    async connect(credentials: TelegramCredentials): Promise<void> {
      status.status = 'connecting';
      
      try {
        // Create the Chat SDK Telegram adapter in polling mode
        chatSdkAdapter = createChatSDKTelegramAdapter({
          botToken: credentials.botToken,
          userName: credentials.botUsername,
          mode: 'polling',
          // Polling options for long-running desktop app
          longPolling: {
            timeout: 30,
            dropPendingUpdates: false,
          },
        });
        
        console.log('[TelegramAdapter] Chat SDK adapter created');
        
        // The adapter starts polling automatically when initialized
        // We need to handle the initialization through the Chat instance
        // For now, mark as connected - the Chat instance handles actual initialization
        status.status = 'connected';
        status.connectedAt = Date.now();
        status.error = undefined;
        
        console.log('[TelegramAdapter] Connected with Chat SDK');
        
      } catch (err) {
        status.status = 'error';
        status.error = (err as Error).message;
        throw err;
      }
    },

    async disconnect(): Promise<void> {
      if (chatSdkAdapter) {
        // Stop polling if running
        try {
          await chatSdkAdapter.stopPolling?.();
        } catch {
          // Ignore errors during cleanup
        }
        chatSdkAdapter = null;
      }
      
      status.status = 'disconnected';
      status.connectedAt = undefined;
      console.log('[TelegramAdapter] Disconnected');
    },

    async sendMessage(chatId: string, text: string): Promise<void> {
      if (!chatSdkAdapter) {
        throw new Error('Telegram adapter not connected');
      }
      
      // Use the Chat SDK's message posting capability
      // The adapter provides thread.post() through the Chat instance
      // For direct messaging, we need to use the underlying Telegram API
      // This will be handled through the Chat instance's sendDM capability
      console.log(`[TelegramAdapter] Would send to ${chatId}: ${text.slice(0, 50)}...`);
    },

    getStatus(): PlatformStatus {
      return { ...status };
    },
    
    getChatSDKAdapter(): ChatSDKTelegramAdapter | null {
      return chatSdkAdapter;
    },
  };
}
