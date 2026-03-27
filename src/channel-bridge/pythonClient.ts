/**
 * Python Client
 * 
 * HTTP client for communicating with the Python backend's internal mobile API.
 */

import type { 
  InboundMessage, 
  MessageSubmitResponse, 
  CommandResponse,
  PairingResponse 
} from './types.js';

export interface PythonClient {
  /**
   * Submit a message to the Python backend for processing.
   */
  submitMessage: (message: InboundMessage) => Promise<MessageSubmitResponse>;
  
  /**
   * Execute a command on the Python backend.
   */
  executeCommand: (command: {
    platform: string;
    senderId: string;
    senderName?: string;
    command: string;
    args: string[];
  }) => Promise<CommandResponse>;
  
  /**
   * Verify a pairing code.
   */
  verifyPairing: (request: {
    platform: string;
    senderId: string;
    displayName: string;
    code: string;
  }) => Promise<PairingResponse>;
  
  /**
   * Check if a user is paired.
   */
  checkPairing: (platform: string, senderId: string) => Promise<boolean>;
  
  /**
   * Make a generic POST request to Python.
   */
  post: <T>(endpoint: string, body: unknown) => Promise<T>;
  
  /**
   * Check if Python backend is available.
   */
  healthCheck: () => Promise<boolean>;
  
  /**
   * Update the base URL (when Python port changes).
   */
  setBaseUrl: (url: string) => void;
}

// Simple logging helper
function debugLog(message: string): void {
  if (process.env.XPDITE_MOBILE_DEBUG_LOGS === '1') {
    console.log(message);
  }
}

export function createPythonClient(initialBaseUrl: string): PythonClient {
  let baseUrl = initialBaseUrl;
  const timeout = 30000; // 30 second timeout for requests

  async function fetchWithTimeout<T>(
    endpoint: string, 
    options: RequestInit
  ): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      const response = await fetch(`${baseUrl}${endpoint}`, {
        ...options,
        signal: controller.signal,
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text}`);
      }

      return await response.json() as T;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  return {
    async submitMessage(message: InboundMessage): Promise<MessageSubmitResponse> {
      // The Python /internal/mobile/message endpoint returns:
      // { success: bool, message: str, tab_id: str | null }
      const result = await fetchWithTimeout<{
        success: boolean;
        message: string;
        tab_id: string | null;
      }>('/internal/mobile/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform: message.platform,
          sender_id: message.senderId,
          message_text: message.message,
          thread_id: message.threadId,
        }),
      });
      
      // Map to expected response format
      return {
        success: result.success,
        queued: result.success, // If successful, message is queued
        error: result.success ? undefined : result.message,
      };
    },

    async executeCommand(command): Promise<CommandResponse> {
      return fetchWithTimeout<CommandResponse>('/internal/mobile/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform: command.platform,
          sender_id: command.senderId,
          command: command.command,
          args: command.args.join(' ') || null,
        }),
      });
    },

    async verifyPairing(request): Promise<PairingResponse> {
      return fetchWithTimeout<PairingResponse>('/internal/mobile/pair/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform: request.platform,
          sender_id: request.senderId,
          display_name: request.displayName,
          code: request.code,
        }),
      });
    },

    async checkPairing(platform: string, senderId: string): Promise<boolean> {
      const result = await fetchWithTimeout<{ paired: boolean }>('/internal/mobile/pair/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          platform,
          sender_id: senderId,
        }),
      });
      return result.paired;
    },

    async post<T>(endpoint: string, body: unknown): Promise<T> {
      return fetchWithTimeout<T>(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    },

    async healthCheck(): Promise<boolean> {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);

        const response = await fetch(`${baseUrl}/internal/mobile/health`, {
          signal: controller.signal,
        });

        clearTimeout(timeoutId);
        return response.ok;
      } catch {
        return false;
      }
    },

    setBaseUrl(url: string): void {
      baseUrl = url;
      debugLog(`[PythonClient] Base URL updated to ${url}`);
    },
  };
}
