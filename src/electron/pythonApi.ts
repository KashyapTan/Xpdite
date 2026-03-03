import { spawn, ChildProcess, SpawnOptions } from 'child_process';
import path from 'path';
import { isDev } from './utils.js';
import { app } from 'electron';
import fs from 'fs';

let pythonProcess: ChildProcess | null = null;
let detectedPort: number = 8000;

/** Full port range the Python backend may bind to (must stay in sync with source/config.py). */
const SERVER_PORT_RANGE = [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009];

function findPythonExecutable(): string {
    if (isDev()) {
        // In development, use the virtual environment
        const venvPython = path.join(process.cwd(), '.venv', 'Scripts', 'python.exe');
        if (fs.existsSync(venvPython)) {
            return venvPython;
        }
        
        // Fallback to system Python
        return 'python';
    } else {
        // In production, use the PyInstaller-generated executable
        const resourcesPath = process.resourcesPath;
        const serverExecutable = path.join(resourcesPath, 'python-server', 'xpdite-server.exe');
        
        if (fs.existsSync(serverExecutable)) {
            return serverExecutable;
        }
        
        // Fallback: try in app directory
        const appPath = path.dirname(process.execPath);
        const fallbackExecutable = path.join(appPath, 'resources', 'python-server', 'xpdite-server.exe');
        
        if (fs.existsSync(fallbackExecutable)) {
            return fallbackExecutable;
        }
        
        throw new Error(`Python server executable not found at: ${serverExecutable} or ${fallbackExecutable}`);
    }
}

function getPythonServerArgs(): string[] {
    if (isDev()) {
        // In development, run as module
        return ['-m', 'source.main'];
    } else {
        // In production, the PyInstaller executable doesn't need arguments
        // as it's a standalone executable
        return [];
    }
}

async function killProcessesOnPorts(ports: number[]): Promise<void> {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    for (const port of ports) {
        try {
            console.log(`Checking for processes on port ${port}...`);
            
            // Find processes using the port on Windows
            const { stdout } = await execAsync(`netstat -ano | findstr :${port}`);
            const lines = stdout.split('\n').filter(line => line.includes('LISTENING'));
            
            for (const line of lines) {
                const parts = line.trim().split(/\s+/);
                const pid = parts[parts.length - 1];
                if (pid && !isNaN(parseInt(pid))) {
                    try {
                        // Check if process exists and get its name
                        const { stdout: processInfo } = await execAsync(`tasklist /FI "PID eq ${pid}" /NH /FO CSV`);
                        const processLines = processInfo.split('\n').filter(line => line.trim());
                        
                        for (const processLine of processLines) {
                            if (processLine.includes(pid)) {
                                const processName = processLine.split(',')[0].replace(/"/g, '').toLowerCase();
                                
                                // Kill if it's Python, our app, or related processes
                                if (processName.includes('python') || 
                                    processName.includes('xpdite') ||
                                    processName.includes('uvicorn') ||
                                    processName.includes('fastapi')) {
                                    console.log(`Terminating process ${processName} (PID: ${pid}) on port ${port}`);
                                    await execAsync(`taskkill /F /PID ${pid}`);
                                } else {
                                    console.log(`Found process ${processName} on port ${port}, but not terminating (not our process)`);
                                }
                            }
                        }
                    } catch {
                        // Process might have already exited, try to kill anyway
                        try {
                            await execAsync(`taskkill /F /PID ${pid}`);
                            console.log(`Force killed process ${pid} on port ${port}`);
                        } catch {
                            // Ignore if we can't kill it
                        }
                    }
                }
            }
        } catch (error) {
            // Port not in use or other error, continue
            console.log(`No processes found on port ${port} or error checking: ${error instanceof Error ? error.message : 'Unknown error'}`);
        }
    }
    
    // Also try to kill any remaining Python processes that might be our server
    try {
        console.log('Checking for any remaining Python processes...');
        const { stdout: allPythonProcesses } = await execAsync(`tasklist /FI "IMAGENAME eq python.exe" /NH /FO CSV`);
        const pythonLines = allPythonProcesses.split('\n').filter(line => line.trim() && line.includes('python.exe'));
        
        for (const line of pythonLines) {
            const parts = line.split(',');
            if (parts.length >= 2) {
                const pid = parts[1].replace(/"/g, '');
                if (pid && !isNaN(parseInt(pid))) {
                    try {
                        // Check command line to see if it's our server
                        const { stdout: cmdLine } = await execAsync(`wmic process where "ProcessId=${pid}" get CommandLine /value`);
                        if (cmdLine.includes('xpdite-server') || 
                            cmdLine.includes('source.main') || 
                            cmdLine.includes('uvicorn') ||
                            cmdLine.includes('fastapi')) {
                            console.log(`Terminating Python server process (PID: ${pid})`);
                            await execAsync(`taskkill /F /PID ${pid}`);
                        }
                    } catch {
                        // Ignore errors when checking command line
                    }
                }
            }
        }
    } catch (error) {
        console.log(`Error checking for Python processes: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
}

export async function startPythonServer(): Promise<void> {
    // Clean up any existing processes on startup (both dev and production)
    console.log('Cleaning up any existing processes before starting...');
    await killProcessesOnPorts(SERVER_PORT_RANGE);
    
    // Wait a moment for cleanup to complete
    await new Promise(resolve => setTimeout(resolve, 1000));
    
    return new Promise((resolve, reject) => {
        const pythonPath = findPythonExecutable();
        const args = getPythonServerArgs();
        
        console.log(`Starting Python server...`);
        console.log(`Python executable: ${pythonPath}`);
        console.log(`Args: ${args.join(' ')}`);

        const options: SpawnOptions = {
            stdio: ['pipe', 'pipe', 'pipe'],
            env: {
                ...process.env,
                // Tell the Python backend where to store user data.
                // In production this resolves to Electron's userData path
                // (e.g. %APPDATA%/Xpdite on Windows). In dev the Python
                // config.py falls back to <PROJECT_ROOT>/user_data.
                ...(!isDev() ? { XPDITE_USER_DATA_DIR: app.getPath('userData') } : {}),
            },
        };

        // Set working directory appropriately
        if (isDev()) {
            options.cwd = process.cwd();
        } else {
            // For PyInstaller executable, we can use the directory where the executable is located
            const executableDir = path.dirname(pythonPath);
            options.cwd = executableDir;
        }

        pythonProcess = spawn(pythonPath, args, options);
        let serverStarted = false;

        if (pythonProcess) {
            pythonProcess.stdout?.on('data', (data) => {
                const output = data.toString();
                console.log(`Python stdout: ${output}`);
                
                // Extract port number from server output
                const portMatch = output.match(/Starting server on port (\d+)/);
                if (portMatch) {
                    detectedPort = parseInt(portMatch[1]);
                    console.log(`Detected server port: ${detectedPort}`);
                }
                
                // Check if server started successfully
                if (output.includes('Starting FastAPI WebSocket server') || 
                    output.includes('Application startup complete')) {
                    serverStarted = true;
                }
            });

            pythonProcess.stderr?.on('data', (data) => {
                const error = data.toString();
                console.error(`Python stderr: ${error}`);
                
                // Handle port binding errors specifically
                if (error.includes('error while attempting to bind on address') || 
                    error.includes('Address already in use')) {
                    console.log('Port conflict detected, Python server will try alternative ports...');
                    return; // Don't reject immediately, let Python handle port finding
                }
                
                // If we see other startup failures, reject immediately
                if (error.includes('ImportError') || 
                    error.includes('ModuleNotFoundError') || 
                    error.includes('SyntaxError')) {
                    if (!serverStarted) {
                        reject(new Error(`Python server failed to start: ${error}`));
                    }
                }
            });

            pythonProcess.on('error', (error) => {
                console.error(`Failed to start Python process: ${error}`);
                reject(error);
            });

            pythonProcess.on('close', (code) => {
                console.log(`Python process exited with code ${code}`);
                pythonProcess = null;
                if (code !== 0 && !serverStarted) {
                    reject(new Error(`Python process exited with code ${code}`));
                }
            });
        }

        // Poll for server readiness: retry every 1s for up to 20s.
        // PyInstaller unpacking can be slow on cold start.
        const POLL_INTERVAL_MS = 1000;
        const MAX_POLL_ATTEMPTS = 20;
        let pollAttempt = 0;

        const pollForServer = () => {
            pollAttempt++;
            const checkServerPorts = async () => {
                try {
                    // Try to find the server on the detected port or fallback ports
                    // Build a de-duplicated list: detected first, then remaining range ports
                    const portsToTry = [detectedPort, ...SERVER_PORT_RANGE.filter(p => p !== detectedPort)];
                    let serverFound = false;
                    
                for (const port of portsToTry) {
                    try {
                        // Test if the server is responding with the health endpoint
                        const controller = new AbortController();
                        const timeoutId = setTimeout(() => controller.abort(), 1000);
                        
                        const response = await fetch(`http://localhost:${port}/api/health`, {
                            method: 'GET',
                            signal: controller.signal
                        }).catch(() => null);
                        
                        clearTimeout(timeoutId);
                        
                        if (response && response.ok) {
                            detectedPort = port;
                            console.log(`Python server found on port ${port}`);
                            serverFound = true;
                            break;
                        }
                    } catch {
                        // Continue to next port
                        continue;
                    }
                }                    if (serverFound || serverStarted) {
                        console.log('Python server started successfully');
                        resolve();
                    } else if (pollAttempt < MAX_POLL_ATTEMPTS) {
                        console.log(`Server not ready yet (attempt ${pollAttempt}/${MAX_POLL_ATTEMPTS}), retrying...`);
                        setTimeout(pollForServer, POLL_INTERVAL_MS);
                    } else {
                        console.error('Python server failed to start - no response on any port after retries');
                        reject(new Error('Python server failed to start'));
                    }
                } catch (error) {
                    console.error('Error checking Python server status:', error);
                    if (pollAttempt < MAX_POLL_ATTEMPTS) {
                        setTimeout(pollForServer, POLL_INTERVAL_MS);
                    } else {
                        reject(error);
                    }
                }
            };
            
            checkServerPorts();
        };

        // Start first poll after 1s to give the process time to begin
        setTimeout(pollForServer, POLL_INTERVAL_MS);
    });
}

let cleaningUp = false;

export async function stopPythonServer(): Promise<void> {
    // Idempotent guard — avoid running concurrent / repeated cleanup.
    if (cleaningUp) return;
    cleaningUp = true;
    console.log('Stopping Python server...');
    
    // First try to gracefully stop the process
    if (pythonProcess) {
        try {
            pythonProcess.kill('SIGTERM');
            
            // Wait a bit for graceful shutdown
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // If still running, force kill
            if (!pythonProcess.killed) {
                pythonProcess.kill('SIGKILL');
            }
        } catch (error) {
            console.error('Error stopping Python process:', error);
        }
        pythonProcess = null;
    }
    
    // Also kill any remaining Python processes on the known ports
    try {
        await killProcessesOnPorts(SERVER_PORT_RANGE);
    } catch (error) {
        console.error('Error killing processes on ports:', error);
    }
    
    console.log('Python server cleanup completed');
}

export function getServerPort(): number {
    return detectedPort;
}

// NOTE: Cleanup is handled by main.ts app-level event handlers.
// Do NOT register additional before-quit / window-all-closed handlers
// here — they would cause duplicate stopPythonServer() calls.
