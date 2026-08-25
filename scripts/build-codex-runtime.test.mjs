import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import {
    copyCodexRuntime,
    getCodexRuntimeDetails,
    resolveCodexRuntimePaths,
} from './build-codex-runtime.mjs';

test('getCodexRuntimeDetails resolves the Windows x64 package and executable', () => {
    assert.deepEqual(getCodexRuntimeDetails('win32', 'x64'), {
        packageName: 'codex-win32-x64',
        targetTriple: 'x86_64-pc-windows-msvc',
        binaryName: 'codex.exe',
    });
});

test('copyCodexRuntime copies the resolved mac runtime into dist-codex-runtime', async () => {
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'xpdite-codex-build-'));
    const fakePackageDir = path.join(tempRoot, 'fake-openai-codex-darwin-arm64');
    const sourceBinary = path.join(
        fakePackageDir,
        'vendor',
        'aarch64-apple-darwin',
        'bin',
        'codex'
    );
    const sourceRipgrep = path.join(
        fakePackageDir,
        'vendor',
        'aarch64-apple-darwin',
        'codex-path',
        'rg'
    );

    await fs.mkdir(path.dirname(sourceBinary), { recursive: true });
    await fs.mkdir(path.dirname(sourceRipgrep), { recursive: true });
    await fs.writeFile(sourceBinary, '#!/bin/sh\n');
    await fs.writeFile(sourceRipgrep, 'rg');

    const copied = await copyCodexRuntime({
        root: tempRoot,
        platform: 'darwin',
        arch: 'arm64',
        resolvePackageDir: () => fakePackageDir,
        resignMacBinary: false,
    });

    const destinationBinary = path.join(
        tempRoot,
        'dist-codex-runtime',
        'aarch64-apple-darwin',
        'bin',
        'codex'
    );
    const destinationRipgrep = path.join(
        tempRoot,
        'dist-codex-runtime',
        'aarch64-apple-darwin',
        'codex-path',
        'rg'
    );

    assert.equal(copied.source, path.join(fakePackageDir, 'vendor', 'aarch64-apple-darwin'));
    assert.equal(copied.destination, path.join(tempRoot, 'dist-codex-runtime', 'aarch64-apple-darwin'));
    assert.equal(await fs.readFile(destinationBinary, 'utf-8'), '#!/bin/sh\n');
    assert.equal(await fs.readFile(destinationRipgrep, 'utf-8'), 'rg');
    assert.equal((await fs.stat(destinationBinary)).mode & 0o777, 0o755);
});

test('resolveCodexRuntimePaths rejects an optional package with no executable', async () => {
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'xpdite-codex-empty-'));
    const fakePackageDir = path.join(tempRoot, 'fake-openai-codex-darwin-arm64');
    await fs.mkdir(
        path.join(fakePackageDir, 'vendor', 'aarch64-apple-darwin', 'bin'),
        { recursive: true },
    );

    assert.throws(
        () => resolveCodexRuntimePaths({
            root: tempRoot,
            platform: 'darwin',
            arch: 'arm64',
            resolvePackageDir: () => fakePackageDir,
        }),
        /OpenAI Codex executable not found/,
    );
});

test('resolveCodexRuntimePaths explains that the helper is bundled when the package is missing', () => {
    assert.throws(
        () =>
            resolveCodexRuntimePaths({
                root: '/tmp/xpdite',
                platform: 'darwin',
                arch: 'arm64',
                resolvePackageDir: () => null,
            }),
        /Run `bun install` to bundle the ChatGPT subscription helper; a separate global Codex install is not required\./
    );
});
