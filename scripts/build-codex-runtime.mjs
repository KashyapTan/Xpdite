import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const require = createRequire(import.meta.url);
const thisFilePath = fileURLToPath(import.meta.url);
const execFileAsync = promisify(execFile);

export function getCodexRuntimeDetails(platform = process.platform, architecture = process.arch) {
    const arch = architecture === 'arm64' ? 'arm64' : 'x64';

    if (platform === 'win32') {
        return {
            packageName: `codex-win32-${arch}`,
            targetTriple: arch === 'arm64' ? 'aarch64-pc-windows-msvc' : 'x86_64-pc-windows-msvc',
            binaryName: 'codex.exe',
        };
    }

    if (platform === 'darwin') {
        return {
            packageName: `codex-darwin-${arch}`,
            targetTriple: arch === 'arm64' ? 'aarch64-apple-darwin' : 'x86_64-apple-darwin',
            binaryName: 'codex',
        };
    }

    return {
        packageName: `codex-linux-${arch}`,
        targetTriple: arch === 'arm64' ? 'aarch64-unknown-linux-musl' : 'x86_64-unknown-linux-musl',
        binaryName: 'codex',
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
    const { packageName, targetTriple, binaryName } = getCodexRuntimeDetails(platform, arch);
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
    // Codex 0.149 moved the executable from codex/<name> to bin/<name>.
    // Keep the legacy lookup so older cached optional packages fail gracefully
    // during lockfile transitions and local development.
    const sourceBinary = [
        path.join(source, 'bin', binaryName),
        path.join(source, 'codex', binaryName),
    ].find((candidate) => existsSync(candidate));
    if (!sourceBinary) {
        throw new Error(`OpenAI Codex executable not found under ${source}`);
    }

    return {
        source,
        sourceBinary,
        binaryRelativePath: path.relative(source, sourceBinary),
        outputRoot,
        destination,
        platform,
    };
}

export async function copyCodexRuntime(options = {}) {
    const { source, sourceBinary, binaryRelativePath, outputRoot, destination, platform } =
        resolveCodexRuntimePaths(options);
    const destinationBinary = path.join(destination, binaryRelativePath);

    await fs.rm(outputRoot, { recursive: true, force: true });
    await fs.mkdir(outputRoot, { recursive: true });
    await fs.cp(source, destination, { recursive: true });
    if (platform !== 'win32') {
        await fs.chmod(destinationBinary, 0o755);
    }
    if (platform === 'darwin' && options.resignMacBinary !== false) {
        // The npm helper's upstream Developer ID can be revoked independently of
        // Xpdite. Re-sign the copied helper ad hoc so local/package smoke tests
        // exercise it; electron-builder applies the final app signature later.
        await execFileAsync('/usr/bin/codesign', [
            '--force',
            '--sign',
            '-',
            destinationBinary,
        ]);
    }

    return { source, sourceBinary, destination, binary: destinationBinary };
}

if (process.argv[1] && path.resolve(process.argv[1]) === thisFilePath) {
    const { source, destination } = await copyCodexRuntime();
    console.log(`Copied OpenAI Codex runtime: ${source} -> ${destination}`);
}
