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
});
