import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';

function getCodexRuntimeDetails() {
    const arch = process.arch === 'arm64' ? 'arm64' : 'x64';

    if (process.platform === 'win32') {
        return {
            packageName: `codex-win32-${arch}`,
            targetTriple: arch === 'arm64' ? 'aarch64-pc-windows-msvc' : 'x86_64-pc-windows-msvc',
        };
    }

    if (process.platform === 'darwin') {
        return {
            packageName: `codex-darwin-${arch}`,
            targetTriple: arch === 'arm64' ? 'aarch64-apple-darwin' : 'x86_64-apple-darwin',
        };
    }

    return {
        packageName: `codex-linux-${arch}`,
        targetTriple: arch === 'arm64' ? 'aarch64-unknown-linux-musl' : 'x86_64-unknown-linux-musl',
    };
}

const root = process.cwd();
const { packageName, targetTriple } = getCodexRuntimeDetails();
const source = path.join(root, 'node_modules', '@openai', packageName, 'vendor', targetTriple);
const outputRoot = path.join(root, 'dist-codex-runtime');
const destination = path.join(outputRoot, targetTriple);

if (!existsSync(source)) {
    throw new Error(`OpenAI Codex runtime not found at ${source}`);
}

await fs.rm(outputRoot, { recursive: true, force: true });
await fs.mkdir(outputRoot, { recursive: true });
await fs.cp(source, destination, { recursive: true });

console.log(`Copied OpenAI Codex runtime: ${source} -> ${destination}`);
