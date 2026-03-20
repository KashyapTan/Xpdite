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
import { discoverServerPort, getWsBaseUrl, resetDiscovery } from '../services/portDiscovery';

type MessageHandler = (data: Record<string, unknown>) => void;

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

    const notifySubscribers = useCallback((data: Record<string, unknown>) => {
        for (const handler of [...subscribersRef.current]) {
            try {
                handler(data);
            } catch (error) {
                console.error('WebSocket subscriber error:', error);
            }
        }
    }, []);

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
        let cancelled = false;
        let reconnectTimeoutId: ReturnType<typeof setTimeout> | null = null;
        /** Reconnect delay with exponential back-off (2 s → 4 s → 8 s … capped at 30 s). */
        let reconnectDelay = 2000;
        const MAX_RECONNECT_DELAY = 30_000;

        const scheduleReconnect = () => {
            if (cancelled || reconnectTimeoutId !== null) {
                return;
            }

            const delay = reconnectDelay;
            reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
            reconnectTimeoutId = setTimeout(() => {
                reconnectTimeoutId = null;
                void connect();
            }, delay);
        };

        const connect = async () => {
            if (cancelled) return;

            try {
                // Discover which port the Python server is actually on.
                await discoverServerPort();
                if (cancelled) return;

                const nextWs = new WebSocket(`${getWsBaseUrl()}/ws`);
                ws = nextWs;
                wsRef.current = nextWs;

                nextWs.onopen = () => {
                    if (cancelled || wsRef.current !== nextWs) return;
                    // Reset back-off on successful connection.
                    reconnectDelay = 2000;
                    setIsConnected(true);
                    // Notify subscribers so they can run connect-time logic
                    // (e.g. App.tsx sends set_capture_mode).
                    notifySubscribers({ type: '__ws_connected' });
                };

                nextWs.onmessage = (event) => {
                    if (cancelled || wsRef.current !== nextWs) return;
                    try {
                        const data = JSON.parse(event.data);
                        notifySubscribers(data);
                    } catch (e) {
                        console.error('Failed to parse WebSocket message:', e);
                    }
                };

                nextWs.onclose = () => {
                    if (cancelled || wsRef.current !== nextWs) return;
                    wsRef.current = null;
                    setIsConnected(false);
                    notifySubscribers({ type: '__ws_disconnected' });
                    // Re-discover port on reconnect in case the server restarted
                    // on a different port.
                    resetDiscovery();
                    scheduleReconnect();
                };

                // onerror is usually followed by onclose, which handles state reset.
                nextWs.onerror = (err) => {
                    if (cancelled || wsRef.current !== nextWs) return;
                    console.error('WebSocket error:', err);
                };
            } catch (error) {
                if (cancelled) return;
                wsRef.current = null;
                setIsConnected(false);
                console.error('WebSocket connect failed:', error);
                resetDiscovery();
                notifySubscribers({ type: '__ws_disconnected' });
                scheduleReconnect();
            }
        };

        void connect();

        return () => {
            cancelled = true;
            if (reconnectTimeoutId !== null) {
                clearTimeout(reconnectTimeoutId);
                reconnectTimeoutId = null;
            }

            const activeWs = wsRef.current ?? ws;
            wsRef.current = null;
            if (activeWs) {
                activeWs.onopen = null;
                activeWs.onmessage = null;
                activeWs.onerror = null;
                activeWs.onclose = null;
                activeWs.close();
            }
        };
    }, [notifySubscribers]);

    return (
        <WebSocketContext.Provider value={{ send, subscribe, isConnected }}>
            {children}
        </WebSocketContext.Provider>
    );
};

// ---- Hook ----

// eslint-disable-next-line react-refresh/only-export-components
export function useWebSocket(): WebSocketContextValue {
    const ctx = useContext(WebSocketContext);
    if (!ctx) {
        throw new Error('useWebSocket must be used within WebSocketProvider');
    }
    return ctx;
}
