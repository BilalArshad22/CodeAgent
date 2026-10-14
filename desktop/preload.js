const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
    // Resolves with {id, result} or {id, error}
    invoke: (method, params) => ipcRenderer.invoke('backend-request', { method, params }),
    onEvent: (callback) => {
        ipcRenderer.on('backend-message', (event, msg) => callback(msg));
        ipcRenderer.on('backend-crash', (event, code) => callback({ error: `Backend crashed with code ${code}` }));
    },
    pickFiles: () => ipcRenderer.invoke('pick-files'),
    pickFolder: () => ipcRenderer.invoke('pick-folder'),
    openPath: (path) => ipcRenderer.invoke('open-path', path),
    isDemo: () => ipcRenderer.invoke('is-demo')
});
