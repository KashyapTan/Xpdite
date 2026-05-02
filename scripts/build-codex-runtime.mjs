import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const thisFilePath = fileURLToPath(import.meta.url);

export function getCodexRuntimeDetails(platform = process.platform, architecture = process.arch) {
    const arch = architecture === 'arm64' ? 'arm64' : 'x64';

    if (platform === 'win32') {
        return {
            packageName: `codex-win32-${arch}`,
            targetTriple: arch === 'arm64' ? 'aarch64-pc-windows-msvc' : 'x86_64-pc-windows-msvc',
        };
    }

    if (platform === 'darwin') {
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

function resolveInstalledPackageDir(packageName) {
    try {
        const packageJsonPath = require.resolve(`@openai/${packageName}/package.json`, {
            paths: [process.cwd()],
        });
        return path.dirname(packageJsonPath);
    } catch {
        return null;
    }
}

export function resolveCodexRuntimePaths({
    root = process.cwd(),
    platform = process.platform,
    arch = process.arch,
    resolvePackageDir = resolveInstalledPackageDir,
} = {}) {
    const { packageName, targetTriple } = getCodexRuntimeDetails(platform, arch);
    const packageDir = resolvePackageDir(packageName);

    if (!packageDir) {
        throw new Error(
            `OpenAI Codex runtime package @openai/${packageName} is not installed. ` +
            'Run `bun install` to bundle the ChatGPT subscription helper; ' +
            'a separate global Codex install is not required.'
        );
    }

    const source = path.join(packageDir, 'vendor', targetTriple);
    const outputRoot = path.join(root, 'dist-codex-runtime');
    const destination = path.join(outputRoot, targetTriple);

    if (!existsSync(source)) {
        throw new Error(`OpenAI Codex runtime not found at ${source}`);
    }

    return { source, outputRoot, destination };
}

export async function copyCodexRuntime(options = {}) {
    const { source, outputRoot, destination } = resolveCodexRuntimePaths(options);

    await fs.rm(outputRoot, { recursive: true, force: true });
    await fs.mkdir(outputRoot, { recursive: true });
    await fs.cp(source, destination, { recursive: true });

    return { source, destination };
}

if (process.argv[1] && path.resolve(process.argv[1]) === thisFilePath) {
    const { source, destination } = await copyCodexRuntime();
    console.log(`Copied OpenAI Codex runtime: ${source} -> ${destination}`);
}
