import { spawn, ChildProcess, SpawnOptions } from 'child_process';
import path from 'path';
import { isDev } from './utils.js';
import { app } from 'electron';
import fs from 'fs';

let pythonProcess: ChildProcess | null = null;
let detectedPort: number = 8000;

/** Callback for XPDITE_BOOT markers parsed from Python stdout. */
type BootMarkerCallback = (marker: { phase: string; message: string; progress: number }) => void;
let bootMarkerCallback: BootMarkerCallback | null = null;

/** Register a listener for structured boot markers from the Python child process. */
export function onBootMarker(cb: BootMarkerCallback) {
    bootMarkerCallback = cb;
}

/** Full port range the Python backend may bind to (must stay in sync with source/config.py). */
const SERVER_PORT_RANGE = [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009];
const HEALTHCHECK_HOST = '127.0.0.1';
const STARTUP_POLL_INTERVAL_MS = 1000;
const STARTUP_HEALTHCHECK_TIMEOUT_MS = 1500;
const STARTUP_TIMEOUT_MS = 90_000;
const PROCESS_RELEASE_GRACE_MS = 350;
const OWNED_PROCESS_NAME_PATTERNS = ['python', 'xpdite', 'uvicorn', 'fastapi'];
const OWNED_COMMAND_LINE_PATTERNS = ['source.main', 'xpdite-server', 'uvicorn', 'fastapi'];
const OWNED_EXECUTABLE_NAMES = ['python.exe', 'pythonw.exe', 'xpdite-server.exe'];

type PythonOutputSource = 'stdout' | 'stderr';
type ProcessRecord = {
    ProcessId?: number;
    Name?: string;
    CommandLine?: string | null;
};

function delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseListeningPidsByPort(netstatOutput: string, ports: Set<number>): Map<number, Set<string>> {
    const pidsByPort = new Map<number, Set<string>>();

    for (const line of netstatOutput.split(/\r?\n/)) {
        if (!line.includes('LISTENING')) {
            continue;
        }

        const parts = line.trim().split(/\s+/);
        if (parts.length < 5) {
            continue;
        }

        const localAddress = parts[1];
        const pid = parts[parts.length - 1];
        const portText = localAddress.split(':').pop();
        const port = portText ? Number.parseInt(portText, 10) : Number.NaN;

        if (!Number.isInteger(port) || !ports.has(port) || !pid) {
            continue;
        }

        const portPids = pidsByPort.get(port) ?? new Set<string>();
        portPids.add(pid);
        pidsByPort.set(port, portPids);
    }

    return pidsByPort;
}

function parseTasklistProcessName(tasklistOutput: string): string | null {
    const firstLine = tasklistOutput
        .split(/\r?\n/)
        .map((line) => line.trim())
        .find(Boolean);

    if (!firstLine || firstLine.startsWith('INFO:')) {
        return null;
    }

    const match = firstLine.match(/^"([^"]+)"/);
    return match?.[1] ?? null;
}

function isOwnedProcess(processName: string | null): boolean {
    if (!processName) {
        return false;
    }

    const normalizedName = processName.toLowerCase();
    return OWNED_PROCESS_NAME_PATTERNS.some((pattern) => normalizedName.includes(pattern));
}

function isOwnedCommandLine(commandLine: string | null | undefined): boolean {
    if (!commandLine) {
        return false;
    }

    const normalizedCommandLine = commandLine.toLowerCase();
    return OWNED_COMMAND_LINE_PATTERNS.some((pattern) => normalizedCommandLine.includes(pattern));
}

function parseProcessRecords(stdout: string): ProcessRecord[] {
    const trimmed = stdout.trim();
    if (!trimmed) {
        return [];
    }

    const parsed = JSON.parse(trimmed) as ProcessRecord | ProcessRecord[];
    return Array.isArray(parsed) ? parsed : [parsed];
}

async function collectKnownBackendPids(
    execAsync: (command: string) => Promise<{ stdout: string; stderr: string }>,
    pidsToKill: Set<string>,
): Promise<void> {
    const command = `powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $processes = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe', 'pythonw.exe', 'xpdite-server.exe') } | Select-Object ProcessId, Name, CommandLine; if ($null -ne $processes) { $processes | ConvertTo-Json -Compress }"`;

    try {
        const { stdout } = await execAsync(command);
        for (const record of parseProcessRecords(stdout)) {
            const processId = record.ProcessId;
            const processName = record.Name?.toLowerCase();

            if (!processId || !processName || !OWNED_EXECUTABLE_NAMES.includes(processName)) {
                continue;
            }

            if (isOwnedCommandLine(record.CommandLine)) {
                pidsToKill.add(String(processId));
            }
        }
    } catch (error) {
        console.warn(`Unable to inspect non-listening backend processes: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
}

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

    const portSet = new Set(ports);
    const pidsToKill = new Set<string>();
    const rangeLabel = `${Math.min(...ports)}-${Math.max(...ports)}`;
    console.log(`Checking for existing backend processes on ports ${rangeLabel}...`);

    try {
        const { stdout } = await execAsync('netstat -ano -p tcp');
        const pidsByPort = parseListeningPidsByPort(stdout, portSet);

        for (const port of ports) {
            const portPids = pidsByPort.get(port);
            if (!portPids || portPids.size === 0) {
                continue;
            }

            console.log(`Found PID(s) ${Array.from(portPids).join(', ')} listening on port ${port}`);
            for (const pid of portPids) {
                pidsToKill.add(pid);
            }
        }
    } catch (error) {
        console.warn(`Unable to inspect listening ports: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }

    await collectKnownBackendPids(execAsync, pidsToKill);

    if (pidsToKill.size === 0) {
        console.log('No existing backend processes found on configured ports.');
        return;
    }

    for (const pid of pidsToKill) {
        try {
            const { stdout: processInfo } = await execAsync(`tasklist /FI "PID eq ${pid}" /NH /FO CSV`);
            const processName = parseTasklistProcessName(processInfo);

            if (!isOwnedProcess(processName)) {
                console.log(`Leaving unrelated process ${processName} (PID: ${pid}) running.`);
                continue;
            }

            console.log(`Terminating process ${processName ?? 'unknown'} (PID: ${pid})`);
            await execAsync(`taskkill /F /T /PID ${pid}`);
        } catch (error) {
            console.warn(`Failed to terminate PID ${pid}: ${error instanceof Error ? error.message : 'Unknown error'}`);
        }
    }

    await delay(PROCESS_RELEASE_GRACE_MS);
}

export async function startPythonServer(): Promise<void> {
    // Clean up any existing processes on startup (both dev and production)
    console.log('Cleaning up any existing processes before starting...');
    await killProcessesOnPorts(SERVER_PORT_RANGE);
    
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
        let settled = false;
        let pollTimerId: ReturnType<typeof setTimeout> | null = null;
        const startupStartedAt = Date.now();

        const safeResolve = () => {
            if (settled) return;
            settled = true;
            if (pollTimerId) clearTimeout(pollTimerId);
            resolve();
        };
        const safeReject = (err: Error) => {
            if (settled) return;
            settled = true;
            if (pollTimerId) clearTimeout(pollTimerId);
            reject(err);
        };

        const processPythonOutputLine = (line: string, source: PythonOutputSource) => {
            // Parse XPDITE_BOOT markers for boot state updates
            const bootMatch = line.match(/XPDITE_BOOT\s+(\{.*\})/);
            if (bootMatch) {
                try {
                    const marker = JSON.parse(bootMatch[1]);
                    bootMarkerCallback?.(marker);
                } catch {
                    console.warn('Malformed XPDITE_BOOT marker:', bootMatch[1]);
                }
            }

            // Extract port number from server output
            const portMatch = line.match(/Starting server on port (\d+)/);
            if (portMatch) {
                detectedPort = parseInt(portMatch[1]);
                console.log(`Detected server port: ${detectedPort}`);
            }

            // Track whether Python thinks it started (used to avoid
            // false-positive rejection on process close, NOT for resolving)
            if (line.includes('Starting FastAPI WebSocket server') ||
                line.includes('Application startup complete')) {
                serverStarted = true;
            }

            if (source === 'stderr') {
                console.error(line);
            } else {
                console.log(line);
            }
        };

        const attachBufferedListener = (
            stream: NodeJS.ReadableStream | null | undefined,
            source: PythonOutputSource,
        ) => {
            if (!stream) {
                return;
            }

            let buffer = '';
            stream.on('data', (data) => {
                buffer += data.toString();
                const lines = buffer.split(/\r?\n/);
                buffer = lines.pop() ?? '';

                for (const rawLine of lines) {
                    const line = rawLine.trimEnd();
                    if (line.trim()) {
                        processPythonOutputLine(line, source);
                    }
                }
            });

            stream.on('end', () => {
                const line = buffer.trim();
                if (line) {
                    processPythonOutputLine(line, source);
                }
            });
        };

        if (pythonProcess) {
            attachBufferedListener(pythonProcess.stdout, 'stdout');
            attachBufferedListener(pythonProcess.stderr, 'stderr');

            pythonProcess.stderr?.on('data', (data) => {
                const error = data.toString();

                // Handle port binding errors specifically
                if (error.includes('error while attempting to bind on address') ||
                    error.includes('Address already in use')) {
                    console.log('Port conflict detected, Python server will try alternative ports...');
                    return;
                }

                // If we see startup-fatal failures, reject immediately
                if (error.includes('ImportError') ||
                    error.includes('ModuleNotFoundError') ||
                    error.includes('SyntaxError')) {
                    if (!serverStarted) {
                        safeReject(new Error(`Python server failed to start: ${error}`));
                    }
                }
            });

            pythonProcess.on('error', (error) => {
                console.error(`Failed to start Python process: ${error}`);
                safeReject(error instanceof Error ? error : new Error(String(error)));
            });

            pythonProcess.on('close', (code) => {
                console.log(`Python process exited with code ${code}`);
                pythonProcess = null;
                if (!settled) {
                    const exitCode = code ?? -1;
                    safeReject(new Error(
                        exitCode === 0 && !serverStarted
                            ? 'Python process exited before the server became ready'
                            : `Python process exited with code ${exitCode}`,
                    ));
                }
            });
        }

        let pollAttempt = 0;

        const pollForServer = () => {
            if (settled) return;
            pollAttempt++;
            const checkServerPorts = async () => {
                try {
                    const portsToTry = [detectedPort, ...SERVER_PORT_RANGE.filter(p => p !== detectedPort)];
                    
                    for (const port of portsToTry) {
                        try {
                            const controller = new AbortController();
                            const timeoutId = setTimeout(() => controller.abort(), STARTUP_HEALTHCHECK_TIMEOUT_MS);
                            
                            const response = await fetch(`http://${HEALTHCHECK_HOST}:${port}/api/health`, {
                                method: 'GET',
                                signal: controller.signal
                            }).catch(() => null);
                            
                            clearTimeout(timeoutId);
                            
                            if (response && response.ok) {
                                detectedPort = port;
                                console.log(`Python server found on port ${port}`);
                                safeResolve();
                                return;
                            }
                        } catch {
                            continue;
                        }
                    }

                    const elapsedMs = Date.now() - startupStartedAt;
                    if (elapsedMs < STARTUP_TIMEOUT_MS) {
                        console.log(
                            `Server not ready yet (attempt ${pollAttempt}, ${Math.ceil(elapsedMs / 1000)}s elapsed), retrying...`,
                        );
                        pollTimerId = setTimeout(pollForServer, STARTUP_POLL_INTERVAL_MS);
                    } else {
                        console.error('Python server failed to start - no response on any port before timeout');
                        safeReject(new Error(`Python server failed to start within ${Math.round(STARTUP_TIMEOUT_MS / 1000)} seconds`));
                    }
                } catch (error) {
                    console.error('Error checking Python server status:', error);
                    const elapsedMs = Date.now() - startupStartedAt;
                    if (elapsedMs < STARTUP_TIMEOUT_MS) {
                        pollTimerId = setTimeout(pollForServer, STARTUP_POLL_INTERVAL_MS);
                    } else {
                        safeReject(error instanceof Error ? error : new Error(String(error)));
                    }
                }
            };
            
            checkServerPorts();
        };

        // Start polling immediately. The health checks already gate readiness,
        // so delaying the first probe only adds dead time to startup.
        pollForServer();
    });
}

let cleaningUp = false;

export async function stopPythonServer(): Promise<void> {
    // Idempotent guard — avoid running concurrent / repeated cleanup.
    if (cleaningUp) return;
    cleaningUp = true;
    console.log('Stopping Python server...');
    try {
    
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
    } finally {
        cleaningUp = false;
    }
}

export function getServerPort(): number {
    return detectedPort;
}

// NOTE: Cleanup is handled by main.ts app-level event handlers.
// Do NOT register additional before-quit / window-all-closed handlers
// here — they would cause duplicate stopPythonServer() calls.
