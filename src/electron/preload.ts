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
    // Meeting recording: system audio loopback (via electron-audio-loopback)
    enableLoopbackAudio: () => ipcRenderer.invoke('enable-loopback-audio'),
    disableLoopbackAudio: () => ipcRenderer.invoke('disable-loopback-audio'),
});
