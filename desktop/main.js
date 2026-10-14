const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let backendProcess = null;
let nextRequestId = 1;
const pending = new Map(); // request id -> resolve(response)

function createMainWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        minWidth: 900,
        minHeight: 600,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true
        },
        backgroundColor: '#0a0a0a'
    });

    if (!app.isPackaged && process.env.NODE_ENV === 'development') {
        mainWindow.loadURL('http://localhost:5173');
    } else {
mainWindow.webContents.on("console-message", (event, level, message, line, sourceId) => { console.log("RENDERER:", message); });

        // DevTools only on request; never in the shipped app or in recordings.
        if (process.env.CODEAGENT_DEVTOOLS === '1') mainWindow.webContents.openDevTools();
        mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
    }
}

function spawnBackend() {
    let backendPath;
    let backendArgs = [];
    
    const isPackaged = app.isPackaged;
    
    if (!isPackaged) {
        // Unpackaged (dev or demo via npm); CODEAGENT_PYTHON overrides the interpreter
        backendPath = process.env.CODEAGENT_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
        backendArgs = ['-m', 'codeagent', 'bridge'];
    } else {
        // Packaged app: PyInstaller onefile binary copied in via extraResources.
        // Without the "bridge" argument the CLI would open the legacy tkinter GUI.
        const ext = process.platform === 'win32' ? '.exe' : '';
        backendPath = path.join(process.resourcesPath, `codeagent-backend${ext}`);
        backendArgs = ['bridge'];
    }

    backendProcess = spawn(backendPath, backendArgs, {
        windowsHide: true,
        env: {
            ...process.env,
            PYTHONPATH: !isPackaged ? path.join(__dirname, '..', 'src') : undefined
        }
    });

    // stdout chunks do not align with lines (large events span several chunks), so buffer
    // until a newline arrives before parsing.
    let stdoutBuffer = '';
    backendProcess.stdout.setEncoding('utf8');
    backendProcess.stdout.on('data', (chunk) => {
        stdoutBuffer += chunk;
        let newline;
        while ((newline = stdoutBuffer.indexOf('\n')) >= 0) {
            const line = stdoutBuffer.slice(0, newline).trim();
            stdoutBuffer = stdoutBuffer.slice(newline + 1);
            if (!line) continue;
            let msg;
            try {
                msg = JSON.parse(line);
            } catch (e) {
                console.error("Failed to parse JSON from backend:", line.slice(0, 200));
                continue;
            }
            if (msg.id !== undefined && pending.has(msg.id)) {
                pending.get(msg.id)(msg);
                pending.delete(msg.id);
            } else if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.webContents.send('backend-message', msg);
            }
        }
    });

    backendProcess.on('error', (err) => {
        console.error(`Failed to start backend (${backendPath}): ${err.message}`);
        failPending(`Backend failed to start: ${err.message}`);
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('backend-crash', err.message);
        }
    });

    backendProcess.stderr.on('data', (data) => {
        console.error(`Backend stderr: ${data.toString()}`);
    });

    backendProcess.on('close', (code) => {
        console.log(`Backend process exited with code ${code}`);
        backendProcess = null;
        failPending(`Backend exited with code ${code}`);
        if (mainWindow && !mainWindow.isDestroyed() && !app.isQuitting) {
            mainWindow.webContents.send('backend-crash', code);
        }
    });
}

function failPending(error) {
    for (const resolve of pending.values()) resolve({ error });
    pending.clear();
}

app.whenReady().then(() => {
    spawnBackend();
    createMainWindow();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createMainWindow();
        }
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('before-quit', () => {
    app.isQuitting = true;
});

app.on('will-quit', () => {
    if (backendProcess) {
        // Closing stdin makes the bridge exit cleanly (PyInstaller onefile runs a child process
        // that a plain kill of the bootloader can leave behind on Windows).
        backendProcess.stdin.end();
        backendProcess.kill();
    }
});

// IPC Handlers
// Request/response: resolves with the backend's {id, result} or {id, error} message.
ipcMain.handle('backend-request', async (event, { method, params }) => {
    if (!backendProcess || backendProcess.killed) {
        if (!app.isQuitting) {
            spawnBackend();
            await new Promise(r => setTimeout(r, 300));
        }
        if (!backendProcess || backendProcess.killed) {
            return { error: 'Backend is not running' };
        }
    }
    const id = nextRequestId++;
    return new Promise((resolve) => {
        pending.set(id, resolve);
        backendProcess.stdin.write(JSON.stringify({ id, method, params: params || {} }) + '\n');
    });
});

ipcMain.handle('pick-files', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
        properties: ['openFile', 'multiSelections'],
        filters: [
            { name: 'Architecture inputs', extensions: ['md', 'markdown', 'puml', 'plantuml', 'json', 'txt'] },
            { name: 'All Files', extensions: ['*'] }
        ]
    });
    return result.filePaths;
});

ipcMain.handle('pick-folder', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
        properties: ['openDirectory']
    });
    if (result.canceled) return null;
    return result.filePaths[0];
});

ipcMain.handle('open-path', async (event, path) => {
    await shell.openPath(path);
});

ipcMain.handle('is-demo', () => {
    return process.argv.includes('--demo') || process.env.CODEAGENT_DEMO === '1';
});
