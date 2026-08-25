import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { pathToFileURL } from 'node:url';

import { copyCodexRuntime } from './build-codex-runtime.mjs';

const PINNED_VERSION = '0.149.1';
const RPC_TIMEOUT_MS = 15_000;

function minimalEnvironment(codexHome) {
    const allowed = [
        'ALL_PROXY', 'APPDATA', 'COMSPEC', 'HOME', 'HOMEDRIVE', 'HOMEPATH',
        'HTTPS_PROXY', 'HTTP_PROXY', 'LANG', 'LOCALAPPDATA', 'NO_PROXY', 'PATH',
        'PATHEXT', 'SSL_CERT_DIR', 'SSL_CERT_FILE', 'SYSTEMROOT', 'TEMP', 'TMP',
        'TMPDIR', 'USER', 'USERNAME', 'USERPROFILE', 'WINDIR',
    ];
    const env = Object.fromEntries(
        allowed.filter((key) => process.env[key]).map((key) => [key, process.env[key]]),
    );
    env.CODEX_HOME = codexHome;
    env.NO_COLOR = '1';
    return env;
}

function exactVersion(userAgent) {
    const match = String(userAgent ?? '').match(/(?:^|[\/\s])v?(\d+\.\d+\.\d+)(?:$|[+\s-])/);
    return match?.[1] ?? null;
}

async function waitForResponse(lines, requestId, child) {
    return await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
            reject(new Error(`Timed out waiting for packaged Codex response ${requestId}`));
        }, RPC_TIMEOUT_MS);
        const onExit = (code, signal) => {
            clearTimeout(timeout);
            reject(new Error(`Packaged Codex exited before handshake (code=${code}, signal=${signal})`));
        };
        const onError = (error) => {
            clearTimeout(timeout);
            reject(new Error(`Could not launch packaged Codex: ${error.message}`));
        };
        child.once('exit', onExit);
        child.once('error', onError);
        const onLine = (line) => {
            let payload;
            try {
                payload = JSON.parse(line);
            } catch {
                return;
            }
            if (payload?.id !== requestId) {
                return;
            }
            clearTimeout(timeout);
            child.off('exit', onExit);
            child.off('error', onError);
            lines.off('line', onLine);
            resolve(payload);
        };
        lines.on('line', onLine);
    });
}

async function stopChild(child) {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.stdin.end();
    const exited = new Promise((resolve) => child.once('exit', resolve));
    const wait = () => new Promise((resolve) => setTimeout(resolve, 3_000, 'timeout'));
    if (await Promise.race([exited, wait()]) === 'timeout') {
        child.kill('SIGTERM');
        if (await Promise.race([exited, wait()]) === 'timeout') {
            child.kill('SIGKILL');
        }
    }
}

export async function smokePackagedCodexRuntime({ root = process.cwd() } = {}) {
    const { binary } = await copyCodexRuntime({ root });
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'xpdite-codex-smoke-'));
    const codexHome = path.join(tempRoot, 'codex-home');
    const cwd = path.join(tempRoot, 'empty-cwd');
    await fs.mkdir(codexHome, { recursive: true, mode: 0o700 });
    await fs.mkdir(cwd, { recursive: true, mode: 0o700 });

    const child = spawn(binary, ['app-server', '--listen', 'stdio://'], {
        cwd,
        env: minimalEnvironment(codexHome),
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
    });
    const lines = readline.createInterface({ input: child.stdout });
    let stderr = '';
    child.stderr.on('data', (chunk) => {
        if (stderr.length < 4_096) stderr += String(chunk).slice(0, 4_096 - stderr.length);
    });

    try {
        const initialize = {
            id: 1,
            method: 'initialize',
            params: {
                clientInfo: { name: 'Xpdite packaged-runtime smoke', version: '0.0.0' },
                capabilities: { experimentalApi: true },
            },
        };
        const responsePromise = waitForResponse(lines, 1, child);
        child.stdin.write(`${JSON.stringify(initialize)}\n`);
        const response = await responsePromise;
        if (response.error || !response.result) {
            throw new Error('Packaged Codex rejected the initialize request');
        }
        const result = response.result;
        if (exactVersion(result.userAgent) !== PINNED_VERSION) {
            throw new Error(`Packaged Codex version mismatch: ${String(result.userAgent)}`);
        }
        const reportedHome = await fs.realpath(String(result.codexHome ?? ''));
        const expectedHome = await fs.realpath(codexHome);
        if (reportedHome !== expectedHome) {
            throw new Error(
                `Packaged Codex did not use the isolated CODEX_HOME (reported ${String(result.codexHome)})`,
            );
        }
        if (!result.platformFamily || !result.platformOs) {
            throw new Error('Packaged Codex returned an incomplete initialize response');
        }
        child.stdin.write(`${JSON.stringify({ method: 'initialized' })}\n`);
        return { userAgent: result.userAgent, platformFamily: result.platformFamily };
    } catch (error) {
        const safeStderr = stderr.replace(/(token|authorization|cookie|secret)[^\s]*/gi, '$1=[REDACTED]');
        if (safeStderr) process.stderr.write(`Packaged Codex stderr: ${safeStderr}\n`);
        throw error;
    } finally {
        lines.close();
        await stopChild(child);
        await fs.rm(tempRoot, { recursive: true, force: true });
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
    const result = await smokePackagedCodexRuntime();
    console.log(`Packaged Codex handshake passed: ${result.userAgent} (${result.platformFamily})`);
}
