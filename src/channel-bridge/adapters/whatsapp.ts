/**
 * WhatsApp Adapter - Chat SDK Wrapper using Baileys
 *
 * Uses the chat-adapter-baileys package which wraps the unofficial Baileys library.
 * 
 * Important caveats (must be communicated to users):
 * 1. This uses Baileys, an unofficial WhatsApp Web API - NOT an official Meta/WhatsApp API
 * 2. Session is tied to a real WhatsApp account via Linked Devices mechanism
 * 3. WhatsApp may disconnect sessions occasionally, requiring re-authentication
 * 4. WhatsApp ToS prohibits unofficial automation - low ban risk for personal use but not zero
 * 
 * Authentication method:
 * - Pairing code: User enters 8-digit code in WhatsApp → Linked Devices
 */

/* eslint-disable react-hooks/rules-of-hooks */
// Note: useMultiFileAuthState is from Baileys, NOT a React hook

import { createBaileysAdapter as createChatSDKBaileysAdapter } from 'chat-adapter-baileys';
import type { BaileysAdapter as ChatSDKBaileysAdapter } from 'chat-adapter-baileys';
import { useMultiFileAuthState } from 'baileys';
import * as path from 'path';
import type {
  PlatformStatus,
  WhatsAppCredentials,
  BridgeMessage
} from '../types.js';

export interface WhatsAppAdapter {
  connect: (credentials: WhatsAppCredentials, userDataDir: string, emitMessage: (msg: BridgeMessage) => void) => Promise<void>;
  disconnect: () => Promise<void>;
  sendMessage: (chatId: string, text: string, replyToMessageId?: string) => Promise<void>;
  getStatus: () => PlatformStatus;
  getChatSDKAdapter: () => ChatSDKBaileysAdapter | null;
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

export function createWhatsAppAdapter(): WhatsAppAdapter {
  let chatSdkAdapter: ChatSDKBaileysAdapter | null = null;
  
  const status: PlatformStatus = {
    platform: 'whatsapp',
    status: 'disconnected',
  };

  return {
    async connect(
      credentials: WhatsAppCredentials, 
      userDataDir: string,
      emitMessage: (msg: BridgeMessage) => void
    ): Promise<void> {
      status.status = 'connecting';
      
      try {
        // Auth state is stored in userDataDir/whatsapp_auth
        const authDir = path.join(userDataDir, 'whatsapp_auth');
        const { state, saveCreds } = await useMultiFileAuthState(authDir);
        
        // Create the Baileys adapter (pairing-code auth only)
        const adapterOptions: Parameters<typeof createChatSDKBaileysAdapter>[0] = {
          auth: { state, saveCreds },
          userName: 'xpdite-bot',
        };

        if (credentials.authMethod === 'pairing_code' && credentials.phoneNumber) {
          // Pairing code authentication
          adapterOptions.phoneNumber = credentials.phoneNumber.replace(/\D/g, ''); // Strip non-digits
          adapterOptions.onPairingCode = (code: string) => {
            debugLog(`[WhatsAppAdapter] Pairing code available: ${code}`);
            // Emit pairing code to Electron for display in settings UI
            emitMessage({ type: 'whatsapp_pairing_code', code });
          };
        }
        
        chatSdkAdapter = createChatSDKBaileysAdapter(adapterOptions);
        
        debugLog('[WhatsAppAdapter] Chat SDK Baileys adapter created');
        
        // Connect to WhatsApp WebSocket
        await chatSdkAdapter.connect();
        
        status.status = 'connected';
        status.connectedAt = Date.now();
        status.error = undefined;
        
        debugLog('[WhatsAppAdapter] Connected to WhatsApp');

      } catch (err) {
        status.status = 'error';
        status.error = (err as Error).message;
        
        errorLog('[WhatsAppAdapter] Connection failed:', err);
        throw err;
      }
    },

    async disconnect(): Promise<void> {
      if (chatSdkAdapter) {
        try {
          await chatSdkAdapter.disconnect?.();
        } catch {
          // Ignore errors during cleanup
        }
        chatSdkAdapter = null;
      }
      
      status.status = 'disconnected';
      status.connectedAt = undefined;
      debugLog('[WhatsAppAdapter] Disconnected');
    },

    async sendMessage(chatId: string, text: string): Promise<void> {
      if (!chatSdkAdapter) {
        throw new Error('WhatsApp adapter not connected');
      }
      
      // Message sending will be handled through the Chat instance
      // The Baileys adapter supports reply() for quoted replies
      debugLog(`[WhatsAppAdapter] Would send to ${chatId}: ${text.slice(0, 50)}...`);
    },

    getStatus(): PlatformStatus {
      return { ...status };
    },
    
    getChatSDKAdapter(): ChatSDKBaileysAdapter | null {
      return chatSdkAdapter;
    },
  };
}
