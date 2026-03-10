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
    getServerPort: () => {
        return ipcRenderer.invoke('get-server-port');
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
});
