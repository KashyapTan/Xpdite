import { contextBridge, ipcRenderer } from 'electron';

console.log('Preload script loaded!');

contextBridge.exposeInMainWorld('electronAPI', {
    setMiniMode: (mini: boolean) => {
        console.log('electronAPI.setMiniMode called with:', mini);
        return ipcRenderer.invoke('set-mini-mode', mini);
    },
    focusWindow: () => {
        console.log('electronAPI.focusWindow called');
        return ipcRenderer.invoke('focus-window');
    },
    openExternalUrl: (url: string) => {
        return ipcRenderer.invoke('open-external-url', url);
    },
    getServerPort: () => {
        return ipcRenderer.invoke('get-server-port');
    },
    getServerToken: () => {
        return ipcRenderer.invoke('get-server-token');
    },
    getBootState: () => {
        return ipcRenderer.invoke('get-boot-state');
    },
    onBootState: (callback: (state: unknown) => void) => {
        const handler = (_event: unknown, state: unknown) => callback(state);
        ipcRenderer.on('boot-state', handler);
        return () => {
            ipcRenderer.removeListener('boot-state', handler);
        };
    },
    retryBoot: () => {
        return ipcRenderer.invoke('retry-boot');
    },
    perfLog: (message: string) => {
        return ipcRenderer.invoke('perf-log', message);
    },
    // Channel Bridge IPC methods
    getChannelBridgePort: () => {
        return ipcRenderer.invoke('get-channel-bridge-port');
    },
    getChannelBridgeStatus: () => {
        return ipcRenderer.invoke('get-channel-bridge-status');
    },
    onChannelBridgeStatus: (callback: (platforms: unknown) => void) => {
        const handler = (_event: unknown, platforms: unknown) => callback(platforms);
        ipcRenderer.on('channel-bridge-status', handler);
        return () => {
            ipcRenderer.removeListener('channel-bridge-status', handler);
        };
    },
    // WhatsApp pairing code listener
    onWhatsAppPairingCode: (callback: (code: string) => void) => {
        const handler = (_event: unknown, code: string) => callback(code);
        ipcRenderer.on('whatsapp-pairing-code', handler);
        return () => {
            ipcRenderer.removeListener('whatsapp-pairing-code', handler);
        };
    },
});
