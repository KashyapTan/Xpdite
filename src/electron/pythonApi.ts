import { spawn, ChildProcess, SpawnOptions } from 'child_process';
import { randomBytes } from 'crypto';
import path from 'path';
import { isDev } from './utils.js';
import { app } from 'electron';
import fs from 'fs';

let pythonProcess: ChildProcess | null = null;
let detectedPort: number = 8000;
const serverToken = randomBytes(32).toString('hex');

/** Callback for XPDITE_BOOT markers parsed from Python stdout. */
type BootMarkerCallback = (marker: { phase: string; message: string; progress: number }) => void;
let bootMarkerCallback: BootMarkerCallback | null = null;

/** Register a listener for structured boot markers from the Python child process. */
export function onBootMarker(cb: BootMarkerCallback) {
    bootMarkerCallback = cb;
}

export function getServerToken(): string {
    return serverToken;
}

/** Full port range the Python backend may bind to (must stay in sync with source/config.py). */
const SERVER_PORT_RANGE = [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009];
const HEALTHCHECK_HOST = '127.0.0.1';
const HEALTHCHECK_PATH = '/api/health';
const SESSION_HEALTHCHECK_PATH = '/api/health/session';
const SERVER_TOKEN_HEADER = 'X-Xpdite-Server-Token';
const STARTUP_POLL_INTERVAL_MS = 250;
const STARTUP_HEALTHCHECK_TIMEOUT_MS = 1500;
const STARTUP_TIMEOUT_MS = 90_000;
const PROCESS_RELEASE_GRACE_MS = 350;
const PROCESS_TERMINATION_GRACE_MS = 500;
const OWNED_PROCESS_NAME_PATTERNS = ['python', 'xpdite'];
const OWNED_COMMAND_LINE_PATTERNS = ['source.main', 'xpdite-server'];
const OWNED_EXECUTABLE_NAMES = ['python.exe', 'pythonw.exe', 'xpdite-server.exe', 'python', 'python3', 'xpdite-server'];

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
    const isWindows = process.platform === 'win32';

    for (const line of netstatOutput.split(/\r?\n/)) {
        if (isWindows) {
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
        } else {
            // macOS/Linux lsof -i -n -P output:
            // COMMAND   PID USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
            // Python  12345 kash    3u  IPv4 0x...      0t0  TCP 127.0.0.1:8000 (LISTEN)
            if (!line.includes('(LISTEN)')) {
                continue;
            }

            const parts = line.trim().split(/\s+/);
            if (parts.length < 9) {
                continue;
            }

            const pid = parts[1];
            const name = parts[8];
            const portText = name.split(':').pop();
            const port = portText ? Number.parseInt(portText, 10) : Number.NaN;

            if (!Number.isInteger(port) || !ports.has(port) || !pid) {
                continue;
            }

            const portPids = pidsByPort.get(port) ?? new Set<string>();
            portPids.add(pid);
            pidsByPort.set(port, portPids);
        }
    }

    return pidsByPort;
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
    const isWindows = process.platform === 'win32';
    const command = isWindows
        ? `powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $processes = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe', 'pythonw.exe', 'xpdite-server.exe') } | Select-Object ProcessId, Name, CommandLine; if ($null -ne $processes) { $processes | ConvertTo-Json -Compress }"`
        : `ps -eo pid,comm,args | grep -E "python|xpdite-server" | grep -v grep`;

    try {
        const { stdout } = await execAsync(command);
        if (isWindows) {
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
        } else {
            // Unify macOS ps -eo pid,comm,args format:
            // PID COMMAND ARGS
            // 12345 python3 source.main
            for (const line of stdout.split(/\r?\n/)) {
                const parts = line.trim().split(/\s+/);
                if (parts.length < 3) continue;
                const pid = parts[0];
                const comm = parts[1];
                const args = parts.slice(2).join(' ');

                if (isOwnedProcess(comm) && isOwnedCommandLine(args)) {
                    pidsToKill.add(pid);
                }
            }
        }
    } catch (error) {
        console.warn(`Unable to inspect non-listening backend processes: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
}

type ProcessIdentity = {
    processName: string | null;
    commandLine: string | null;
};

async function getProcessIdentityByPid(
    pid: string,
    execAsync: (command: string) => Promise<{ stdout: string; stderr: string }>,
): Promise<ProcessIdentity> {
    const isWindows = process.platform === 'win32';
    if (isWindows) {
        const command = `powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $proc = Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}' | Select-Object Name, CommandLine; if ($null -ne $proc) { $proc | ConvertTo-Json -Compress }"`;
        const { stdout } = await execAsync(command);
        const records = parseProcessRecords(stdout);
        const record = records[0];
        return {
            processName: record?.Name ?? null,
            commandLine: record?.CommandLine ?? null,
        };
    }

    const [{ stdout: processNameStdout }, { stdout: commandLineStdout }] = await Promise.all([
        execAsync(`ps -p ${pid} -o comm=`),
        execAsync(`ps -p ${pid} -o args=`),
    ]);

    const processName = processNameStdout.trim() || null;
    const commandLine = commandLineStdout.trim() || null;
    return { processName, commandLine };
}

async function terminateOwnedProcessByPid(
    pid: string,
    execAsync: (command: string) => Promise<{ stdout: string; stderr: string }>,
): Promise<void> {
    const isWindows = process.platform === 'win32';
    if (isWindows) {
        try {
            await execAsync(`taskkill /T /PID ${pid}`);
        } catch {
            await execAsync(`taskkill /F /T /PID ${pid}`);
        }
        return;
    }

    await execAsync(`kill -15 ${pid}`);
    await delay(PROCESS_TERMINATION_GRACE_MS);

    try {
        await execAsync(`kill -0 ${pid}`);
        await execAsync(`kill -9 ${pid}`);
    } catch {
        // Process exited after SIGTERM.
    }
}

function findPythonExecutable(): string {
    const isWindows = process.platform === 'win32';
    if (isDev()) {
        // In development, use the virtual environment
        const venvPythonStr = isWindows
            ? path.join(process.cwd(), '.venv', 'Scripts', 'python.exe')
            : path.join(process.cwd(), '.venv', 'bin', 'python');

        if (fs.existsSync(venvPythonStr)) {
            return venvPythonStr;
        }

        // Fallback to system Python
        return isWindows ? 'python' : 'python3';
    } else {
        const exeName = isWindows ? 'xpdite-server.exe' : 'xpdite-server';
        const resourcesPath = process.resourcesPath;
        const appPath = path.dirname(process.execPath);

        const candidates = [
            path.join(resourcesPath, 'python-server', exeName),
            path.join(resourcesPath, 'python-server', 'xpdite-server', exeName),
            path.join(appPath, 'resources', 'python-server', exeName),
            path.join(appPath, 'resources', 'python-server', 'xpdite-server', exeName),
        ];

        for (const candidate of candidates) {
            if (fs.existsSync(candidate)) {
                return candidate;
            }
        }

        throw new Error(`Python server executable not found. Checked: ${candidates.join(', ')}`);
    }
}

function waitForChildProcessExit(
    childProcess: ChildProcess,
    timeoutMs: number,
): Promise<boolean> {
    if (childProcess.exitCode !== null || childProcess.signalCode !== null) {
        return Promise.resolve(true);
    }

    return new Promise((resolve) => {
        let settled = false;

        const cleanup = () => {
            childProcess.off('close', handleExit);
            childProcess.off('exit', handleExit);
            childProcess.off('error', handleError);
            clearTimeout(timeoutId);
        };

        const finish = (value: boolean) => {
            if (settled) {
                return;
            }
            settled = true;
            cleanup();
            resolve(value);
        };

        const handleExit = () => finish(true);
        const handleError = () => finish(false);
        const timeoutId = setTimeout(() => finish(false), timeoutMs);

        childProcess.once('close', handleExit);
        childProcess.once('exit', handleExit);
        childProcess.once('error', handleError);
    });
}

async function terminateTrackedPythonProcess(childProcess: ChildProcess): Promise<void> {
    const pid = childProcess.pid;
    if (!pid) {
        return;
    }

    if (process.platform === 'win32') {
        const { exec } = await import('child_process');
        const { promisify } = await import('util');
        const execAsync = promisify(exec);
        try {
            await execAsync(`taskkill /T /PID ${pid}`);
        } catch {
            await execAsync(`taskkill /F /T /PID ${pid}`);
        }

        const exited = await waitForChildProcessExit(childProcess, 1_500);
        if (!exited) {
            try {
                await execAsync(`taskkill /F /T /PID ${pid}`);
            } catch {
                // Ignore repeated force-kill failures and continue with port cleanup.
            }
            await waitForChildProcessExit(childProcess, 1_500);
        }
        return;
    }

    try {
        childProcess.kill('SIGTERM');
    } catch {
        return;
    }

    const exited = await waitForChildProcessExit(childProcess, 1_000);
    if (exited) {
        return;
    }

    try {
        childProcess.kill('SIGKILL');
    } catch {
        return;
    }

    await waitForChildProcessExit(childProcess, 1_000);
}

async function probeServerHealth(
    port: number,
    sessionToken?: string,
): Promise<boolean> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), STARTUP_HEALTHCHECK_TIMEOUT_MS);
    const headers = sessionToken
        ? { [SERVER_TOKEN_HEADER]: sessionToken }
        : undefined;
    const healthPath = sessionToken ? SESSION_HEALTHCHECK_PATH : HEALTHCHECK_PATH;

    try {
        const response = await fetch(`http://${HEALTHCHECK_HOST}:${port}${healthPath}`, {
            method: 'GET',
            headers,
            signal: controller.signal,
        }).catch(() => null);

        return Boolean(response?.ok);
    } finally {
        clearTimeout(timeoutId);
    }
}

function findRuntimeRoot(): string {
    const resourcesPath = process.resourcesPath;
    const primary = path.join(resourcesPath, 'python-runtime');
    if (fs.existsSync(primary)) {
        return primary;
    }

    const appPath = path.dirname(process.execPath);
    const fallback = path.join(appPath, 'resources', 'python-runtime');
    if (fs.existsSync(fallback)) {
        return fallback;
    }

    throw new Error(`Bundled Python runtime not found at: ${primary} or ${fallback}`);
}

function findBundledChildPythonExecutable(runtimeRoot: string): string {
    const candidates = process.platform === 'win32'
        ? [
            path.join(runtimeRoot, '.venv', 'Scripts', 'python.exe'),
            path.join(runtimeRoot, 'python.exe'),
          ]
        : [
            path.join(runtimeRoot, '.venv', 'bin', 'python'),
            path.join(runtimeRoot, '.venv', 'bin', 'python3'),
            path.join(runtimeRoot, 'bin', 'python3'),
            path.join(runtimeRoot, 'bin', 'python'),
          ];

    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }

    throw new Error(`Bundled child Python interpreter not found under: ${runtimeRoot}`);
}

function findRuntimeEnvFile(): string {
    const resourcesPath = process.resourcesPath;
    const primary = path.join(resourcesPath, 'runtime-config', 'google-oauth.env');
    if (fs.existsSync(primary)) {
        return primary;
    }

    const appPath = path.dirname(process.execPath);
    const fallback = path.join(appPath, 'resources', 'runtime-config', 'google-oauth.env');
    if (fs.existsSync(fallback)) {
        return fallback;
    }

    throw new Error(`Runtime env file not found at: ${primary} or ${fallback}`);
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
        const isWindows = process.platform === 'win32';
        const netstatCmd = isWindows ? 'netstat -ano -p tcp' : 'lsof -iTCP -sTCP:LISTEN -P -n';
        const { stdout } = await execAsync(netstatCmd);
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
            const { processName, commandLine } = await getProcessIdentityByPid(pid, execAsync);

            if (!isOwnedProcess(processName) || !isOwnedCommandLine(commandLine)) {
                console.log(`Leaving unrelated process ${processName} (PID: ${pid}) running.`);
                continue;
            }

            console.log(`Terminating process ${processName ?? 'unknown'} (PID: ${pid})`);
            await terminateOwnedProcessByPid(pid, execAsync);
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
        const runtimeRoot = !isDev() ? findRuntimeRoot() : undefined;
        const runtimeEnvFile = !isDev() ? findRuntimeEnvFile() : undefined;
        const childPythonExecutable = runtimeRoot ? findBundledChildPythonExecutable(runtimeRoot) : undefined;
        
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
                ...(!isDev()
                    ? {
                        XPDITE_USER_DATA_DIR: app.getPath('userData'),
                        XPDITE_RUNTIME_ROOT: runtimeRoot,
                        XPDITE_RUNTIME_ENV_FILE: runtimeEnvFile,
                        XPDITE_CHILD_PYTHON_EXECUTABLE: childPythonExecutable,
                      }
                    : {}),
                XPDITE_SERVER_TOKEN: serverToken,
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
                            if (await probeServerHealth(port, serverToken)) {
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
    const trackedProcess = pythonProcess;
    pythonProcess = null;

    if (trackedProcess) {
        try {
            await terminateTrackedPythonProcess(trackedProcess);
        } catch (error) {
            console.error('Error stopping Python process:', error);
        }
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
