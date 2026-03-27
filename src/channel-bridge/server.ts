/**
 * Channel Bridge HTTP Server
 * 
 * Provides HTTP endpoints for:
 * - Python backend to send messages to platforms
 * - Health checks
 * - Command registration
 */

import { createServer, IncomingMessage, ServerResponse } from 'node:http';
import type { 
  SendMessageRequest, 
  HealthResponse, 
  PlatformStatus,
  Platform,
  OutboundMessageType 
} from './types.js';

export interface ServerDependencies {
  sendToPlatform: (
    platform: Platform, 
    senderId: string, 
    message: string, 
    messageType: OutboundMessageType,
    replyToMessageId?: string,
    threadId?: string,
  ) => Promise<string | undefined>;
  startTypingIndicator: (
    platform: Platform,
    threadId: string | undefined,
  ) => Promise<void>;
  editPlatformMessage: (
    platform: Platform,
    threadId: string,
    messageId: string,
    content: string,
  ) => Promise<void>;
  getPlatformStatuses: () => PlatformStatus[];
}

export interface BridgeServer {
  start: (port: number) => Promise<number>;
  stop: () => Promise<void>;
  getPort: () => number;
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

export function createBridgeServer(deps: ServerDependencies): BridgeServer {
  let server: ReturnType<typeof createServer> | null = null;
  let actualPort = 0;
  const startTime = Date.now();

  async function parseBody<T>(req: IncomingMessage): Promise<T> {
    return new Promise((resolve, reject) => {
      const chunks: Buffer[] = [];
      req.on('data', (chunk: Buffer) => chunks.push(chunk));
      req.on('end', () => {
        try {
          const body = Buffer.concat(chunks).toString('utf8');
          resolve(JSON.parse(body) as T);
        } catch {
          reject(new Error('Invalid JSON body'));
        }
      });
      req.on('error', reject);
    });
  }

  function sendJson(res: ServerResponse, status: number, data: unknown): void {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(data));
  }

  function sendError(res: ServerResponse, status: number, message: string): void {
    sendJson(res, status, { error: message });
  }

  async function handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', `http://localhost:${actualPort}`);
    const path = url.pathname;
    const method = req.method ?? 'GET';

    // CORS headers for local development
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    try {
      // Health check
      if (path === '/health' && method === 'GET') {
        const response: HealthResponse = {
          status: 'ok',
          uptime: Date.now() - startTime,
          platforms: deps.getPlatformStatuses(),
        };
        sendJson(res, 200, response);
        return;
      }

      // Send message to platform (legacy endpoint)
      if (path === '/send' && method === 'POST') {
        const body = await parseBody<SendMessageRequest>(req);
        
        if (!body.platform || !body.senderId || !body.message) {
          sendError(res, 400, 'Missing required fields: platform, senderId, message');
          return;
        }

        await deps.sendToPlatform(
          body.platform,
          body.senderId,
          body.message,
          body.messageType ?? 'final_response',
          body.replyToMessageId
        );

        sendJson(res, 200, { success: true });
        return;
      }

      // Outbound message relay from Python backend
      if (path === '/outbound' && method === 'POST') {
        const body = await parseBody<{
          platform: Platform;
          sender_id: string;
          message_type: 'ack' | 'status' | 'response' | 'error';
          content: string;
          thread_id?: string;
        }>(req);
        
        if (!body.platform || !body.sender_id || !body.content) {
          sendError(res, 400, 'Missing required fields: platform, sender_id, content');
          return;
        }

        // Map Python message types to our OutboundMessageType
        const typeMap: Record<string, OutboundMessageType> = {
          'ack': 'ack',
          'status': 'status_update',
          'response': 'final_response',
          'error': 'final_response',
        };

        const messageId = await deps.sendToPlatform(
          body.platform,
          body.sender_id,
          body.content,
          typeMap[body.message_type] ?? 'final_response',
          undefined,
          body.thread_id
        );

        sendJson(res, 200, { success: true, message_id: messageId });
        return;
      }

      // Typing indicator from Python backend
      if (path === '/outbound/typing' && method === 'POST') {
        const body = await parseBody<{
          platform: Platform;
          thread_id: string;
        }>(req);
        
        if (!body.platform || !body.thread_id) {
          sendError(res, 400, 'Missing required fields: platform, thread_id');
          return;
        }

        await deps.startTypingIndicator(body.platform, body.thread_id);
        sendJson(res, 200, { success: true });
        return;
      }

      // Edit existing message (for streaming updates)
      if (path === '/outbound/edit' && method === 'POST') {
        const body = await parseBody<{
          platform: Platform;
          thread_id: string;
          message_id: string;
          content: string;
        }>(req);
        
        if (!body.platform || !body.thread_id || !body.message_id || !body.content) {
          sendError(res, 400, 'Missing required fields: platform, thread_id, message_id, content');
          return;
        }

        await deps.editPlatformMessage(body.platform, body.thread_id, body.message_id, body.content);
        sendJson(res, 200, { success: true });
        return;
      }

      // Platform statuses
      if (path === '/status' && method === 'GET') {
        sendJson(res, 200, { platforms: deps.getPlatformStatuses() });
        return;
      }

      // 404 for unknown routes
      sendError(res, 404, `Not found: ${method} ${path}`);

    } catch (err) {
      errorLog('[BridgeServer] Error handling request:', err);
      sendError(res, 500, err instanceof Error ? err.message : 'Internal server error');
    }
  }

  return {
    async start(port: number): Promise<number> {
      return new Promise((resolve, reject) => {
        server = createServer((req, res) => {
          handleRequest(req, res).catch((err) => {
            errorLog('[BridgeServer] Unhandled error:', err);
            if (!res.headersSent) {
              sendError(res, 500, 'Internal server error');
            }
          });
        });

        server.on('error', (err: NodeJS.ErrnoException) => {
          if (err.code === 'EADDRINUSE') {
            // Port in use, try next port
            debugLog(`[BridgeServer] Port ${port} in use, trying ${port + 1}`);
            server?.close();
            resolve(this.start(port + 1));
          } else {
            reject(err);
          }
        });

        server.listen(port, '127.0.0.1', () => {
          actualPort = port;
          debugLog(`[BridgeServer] Listening on port ${port}`);
          resolve(port);
        });
      });
    },

    async stop(): Promise<void> {
      return new Promise((resolve) => {
        if (server) {
          server.close(() => {
            server = null;
            actualPort = 0;
            resolve();
          });
        } else {
          resolve();
        }
      });
    },

    getPort(): number {
      return actualPort;
    },
  };
}
