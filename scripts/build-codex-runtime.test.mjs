import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { copyCodexRuntime, resolveCodexRuntimePaths } from './build-codex-runtime.mjs';

test('copyCodexRuntime copies the resolved mac runtime into dist-codex-runtime', async () => {
    const tempRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'xpdite-codex-build-'));
    const fakePackageDir = path.join(tempRoot, 'fake-openai-codex-darwin-arm64');
    const sourceBinary = path.join(
        fakePackageDir,
        'vendor',
        'aarch64-apple-darwin',
        'codex',
        'codex'
    );
    const sourceRipgrep = path.join(
        fakePackageDir,
        'vendor',
        'aarch64-apple-darwin',
        'path',
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
    });

    const destinationBinary = path.join(
        tempRoot,
        'dist-codex-runtime',
        'aarch64-apple-darwin',
        'codex',
        'codex'
    );
    const destinationRipgrep = path.join(
        tempRoot,
        'dist-codex-runtime',
        'aarch64-apple-darwin',
        'path',
        'rg'
    );

    assert.equal(copied.source, path.join(fakePackageDir, 'vendor', 'aarch64-apple-darwin'));
    assert.equal(copied.destination, path.join(tempRoot, 'dist-codex-runtime', 'aarch64-apple-darwin'));
    assert.equal(await fs.readFile(destinationBinary, 'utf-8'), '#!/bin/sh\n');
    assert.equal(await fs.readFile(destinationRipgrep, 'utf-8'), 'rg');
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
