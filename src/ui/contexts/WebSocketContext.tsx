/**
 * WebSocketContext.
 *
 * Manages the single WebSocket connection to the Python backend.
 * Lives at the Layout level so the connection persists across route changes.
 *
 * Provides:
 *  - send(msg)   — send a JSON message (no-ops if not connected)
 *  - subscribe(handler) — register a message handler, returns unsubscribe fn
 *  - isConnected — current connection state
 *
 * All route-level components (App, MeetingRecorder, MeetingAlbum, etc.)
 * subscribe for the messages they care about. The provider does not interpret
 * message content — it's a pure pub/sub transport.
 */
import React, { createContext, useContext, useRef, useState, useCallback, useEffect } from 'react';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type MessageHandler = (data: Record<string, any>) => void;

interface WebSocketContextValue {
    /** Send a JSON-serialisable message over the WebSocket. */
    send: (msg: Record<string, unknown>) => void;
    /** Register a handler for incoming messages. Returns an unsubscribe function. */
    subscribe: (handler: MessageHandler) => () => void;
    /** Whether the WebSocket is currently connected. */
    isConnected: boolean;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

// ---- Provider ----

interface ProviderProps {
    children: React.ReactNode;
}

export const WebSocketProvider: React.FC<ProviderProps> = ({ children }) => {
    const wsRef = useRef<WebSocket | null>(null);
    const [isConnected, setIsConnected] = useState(false);
    const subscribersRef = useRef<Set<MessageHandler>>(new Set());

    const send = useCallback((msg: Record<string, unknown>) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(msg));
        }
    }, []);

    const subscribe = useCallback((handler: MessageHandler) => {
        subscribersRef.current.add(handler);
        return () => { subscribersRef.current.delete(handler); };
    }, []);

    useEffect(() => {
        let ws: WebSocket | null = null;

        const connect = () => {
            ws = new WebSocket('ws://localhost:8000/ws');
            wsRef.current = ws;

            ws.onopen = () => {
                setIsConnected(true);
                // Notify subscribers so they can run connect-time logic
                // (e.g. App.tsx sends set_capture_mode).
                // Snapshot the set to guard against subscribe/unsubscribe during iteration.
                for (const handler of [...subscribersRef.current]) {
                    handler({ type: '__ws_connected' });
                }
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    for (const handler of [...subscribersRef.current]) {
                        handler(data);
                    }
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };

            ws.onclose = () => {
                setIsConnected(false);
                // Notify subscribers of disconnection
                for (const handler of [...subscribersRef.current]) {
                    handler({ type: '__ws_disconnected' });
                }
                setTimeout(connect, 2000);
            };

            // onerror is always followed by onclose, which handles state reset.
            ws.onerror = (err) => {
                console.error('WebSocket error:', err);
            };
        };

        connect();

        return () => {
            if (ws) {
                ws.onclose = null;
                ws.close();
            }
        };
    }, []);

    return (
        <WebSocketContext.Provider value={{ send, subscribe, isConnected }}>
            {children}
        </WebSocketContext.Provider>
    );
};

// ---- Hook ----

export function useWebSocket(): WebSocketContextValue {
    const ctx = useContext(WebSocketContext);
    if (!ctx) {
        throw new Error('useWebSocket must be used within WebSocketProvider');
    }
    return ctx;
}
