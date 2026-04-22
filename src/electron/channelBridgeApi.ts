/**
 * Channel Bridge Process Management
 * 
 * Spawns and manages the Channel Bridge TypeScript service process,
 * similar to how pythonApi.ts manages the Python server.
 */

import { spawn, fork, ChildProcess, SpawnOptions, ForkOptions } from 'child_process';
import path from 'path';
import { isDev } from './utils.js';
import { app } from 'electron';
import fs from 'fs';

let bridgeProcess: ChildProcess | null = null;
let detectedPort: number = 9000;

/** Default port for the Channel Bridge */
const DEFAULT_BRIDGE_PORT = 9000;
const COMPILED_CHANNEL_BRIDGE_ENTRYPOINT = 'index.cjs';

/** Callback for status messages from the Channel Bridge */
type BridgeMessageCallback = (message: {
    type: string;
    port?: number;
    platforms?: Array<{ platform: string; status: string; error?: string }>;
    error?: string;
    qrCode?: string;
    code?: string;
}) => void;

let bridgeMessageCallback: BridgeMessageCallback | null = null;

/** Register a listener for messages from the Channel Bridge process. */
export function onBridgeMessage(cb: BridgeMessageCallback): void {
    bridgeMessageCallback = cb;
}

/** Find the Channel Bridge executable */
function findBridgeExecutable(): { executable: string; args: string[]; useFork?: boolean } {
    if (isDev()) {
        // In development, run via bun
        const scriptPath = path.join(process.cwd(), 'src', 'channel-bridge', 'index.ts');
        
        if (fs.existsSync(scriptPath)) {
            return {
                executable: 'bun',
                args: ['run', scriptPath],
            };
        }
        
        // Fallback to compiled JS
        const compiledPath = path.join(process.cwd(), 'dist-channel-bridge', COMPILED_CHANNEL_BRIDGE_ENTRYPOINT);
        if (fs.existsSync(compiledPath)) {
            return {
                executable: 'node',
                args: [compiledPath],
            };
        }
        
        throw new Error(`Channel Bridge script not found at: ${scriptPath}`);
    } else {
        // In production, use the bundled JS 
        // The Channel Bridge uses Node.js APIs so we run it via fork() from Electron
        const resourcesPath = process.resourcesPath;
        const bundledJs = path.join(resourcesPath, 'channel-bridge', COMPILED_CHANNEL_BRIDGE_ENTRYPOINT);
        
        if (fs.existsSync(bundledJs)) {
            // Use fork for production - Electron can fork child Node.js processes
            return {
                executable: bundledJs,
                args: [],
                useFork: true,
            };
        }
        
        throw new Error(`Channel Bridge not found at: ${bundledJs}`);
    }
}

export async function startChannelBridge(pythonPort: number): Promise<void> {
    return new Promise((resolve, reject) => {
        const { executable, args, useFork } = findBridgeExecutable();
        
        console.log(`Starting Channel Bridge...`);
        console.log(`Executable: ${executable} ${args.join(' ')} (useFork: ${useFork ?? false})`);
        
        const envVars = {
            ...process.env,
            XPDITE_USER_DATA_DIR: isDev() ? path.join(process.cwd(), 'user_data') : app.getPath('userData'),
            PYTHON_SERVER_PORT: String(pythonPort),
            BRIDGE_PORT: String(DEFAULT_BRIDGE_PORT),
        };
        
        if (useFork) {
            // In production, use fork() which runs the script in a child Node.js process
            const forkOptions: ForkOptions = {
                stdio: ['pipe', 'pipe', 'pipe', 'ipc'],
                env: envVars,
            };
            bridgeProcess = fork(executable, args, forkOptions);
        } else {
            // In development, use spawn() with bun or node
            const spawnOptions: SpawnOptions = {
                stdio: ['pipe', 'pipe', 'pipe'],
                env: envVars,
                cwd: isDev() ? process.cwd() : undefined,
            };
            bridgeProcess = spawn(executable, args, spawnOptions);
        }
        
        let settled = false;
        
        const safeResolve = () => {
            if (settled) return;
            settled = true;
            resolve();
        };
        
        const safeReject = (err: Error) => {
            if (settled) return;
            settled = true;
            reject(err);
        };
        
        // Set a startup timeout
        const timeoutId = setTimeout(() => {
            safeReject(new Error('Channel Bridge failed to start within 30 seconds'));
        }, 30000);
        
        const processBridgeOutputLine = (line: string) => {
            // Parse CHANNEL_BRIDGE_MSG markers for structured messages
            const msgMatch = line.match(/CHANNEL_BRIDGE_MSG\s+(\{.*\})/);
            if (msgMatch) {
                try {
                    const message = JSON.parse(msgMatch[1]);
                    
                    // Handle ready message
                    if (message.type === 'ready') {
                        detectedPort = message.port ?? DEFAULT_BRIDGE_PORT;
                        console.log(`Channel Bridge ready on port ${detectedPort}`);
                        clearTimeout(timeoutId);
                        safeResolve();
                    }
                    
                    // Forward all messages to callback
                    bridgeMessageCallback?.(message);
                } catch {
                    console.warn('Malformed CHANNEL_BRIDGE_MSG:', msgMatch[1]);
                }
            }
            
            console.log(`[ChannelBridge] ${line}`);
        };
        
        const attachBufferedListener = (
            stream: NodeJS.ReadableStream | null | undefined,
            isError: boolean = false,
        ) => {
            if (!stream) return;
            
            let buffer = '';
            stream.on('data', (data) => {
                buffer += data.toString();
                const lines = buffer.split(/\r?\n/);
                buffer = lines.pop() ?? '';
                
                for (const rawLine of lines) {
                    const line = rawLine.trimEnd();
                    if (line.trim()) {
                        if (isError) {
                            console.error(`[ChannelBridge] ${line}`);
                        } else {
                            processBridgeOutputLine(line);
                        }
                    }
                }
            });
            
            stream.on('end', () => {
                const line = buffer.trim();
                if (line) {
                    if (isError) {
                        console.error(`[ChannelBridge] ${line}`);
                    } else {
                        processBridgeOutputLine(line);
                    }
                }
            });
        };
        
        if (bridgeProcess) {
            attachBufferedListener(bridgeProcess.stdout, false);
            attachBufferedListener(bridgeProcess.stderr, true);
            
            bridgeProcess.on('error', (error) => {
                console.error(`Failed to start Channel Bridge process: ${error}`);
                clearTimeout(timeoutId);
                safeReject(error instanceof Error ? error : new Error(String(error)));
            });
            
            bridgeProcess.on('close', (code) => {
                console.log(`Channel Bridge process exited with code ${code}`);
                bridgeProcess = null;
                if (!settled) {
                    clearTimeout(timeoutId);
                    safeReject(new Error(`Channel Bridge process exited with code ${code}`));
                }
            });
        }
    });
}

let cleaningUp = false;

export async function stopChannelBridge(): Promise<void> {
    if (cleaningUp) return;
    cleaningUp = true;
    
    console.log('Stopping Channel Bridge...');
    
    try {
        if (bridgeProcess) {
            try {
                bridgeProcess.kill('SIGTERM');
                
                // Wait for graceful shutdown
                await new Promise(resolve => setTimeout(resolve, 1000));
                
                // Force kill if still running
                if (!bridgeProcess.killed) {
                    bridgeProcess.kill('SIGKILL');
                }
            } catch (error) {
                console.error('Error stopping Channel Bridge process:', error);
            }
            bridgeProcess = null;
        }
        
        console.log('Channel Bridge cleanup completed');
    } finally {
        cleaningUp = false;
    }
}

export function getChannelBridgePort(): number {
    return detectedPort;
}

export function isChannelBridgeRunning(): boolean {
    return bridgeProcess !== null && !bridgeProcess.killed;
}

/**
 * Send a message to the Channel Bridge via its HTTP API.
 * Used for sending messages from Python to platforms.
 */
export async function sendToChannelBridge(
    platform: string,
    senderId: string,
    message: string,
    messageType: 'ack' | 'status_update' | 'final_response' | 'error',
    replyToMessageId?: string,
): Promise<void> {
    const url = `http://127.0.0.1:${detectedPort}/send`;
    
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            platform,
            senderId,
            message,
            messageType,
            replyToMessageId,
        }),
    });
    
    if (!response.ok) {
        const text = await response.text();
        throw new Error(`Channel Bridge send failed: ${text}`);
    }
}

/**
 * Get the status of all connected platforms.
 */
export async function getChannelBridgeStatus(): Promise<{
    platforms: Array<{ platform: string; status: string; error?: string }>;
}> {
    const url = `http://127.0.0.1:${detectedPort}/status`;
    
    try {
        const response = await fetch(url);
        if (!response.ok) {
            return { platforms: [] };
        }
        return await response.json();
    } catch {
        return { platforms: [] };
    }
}
