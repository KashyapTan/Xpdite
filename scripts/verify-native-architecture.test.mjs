import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  parseLipoArchitectures,
  parseOtoolDependencies,
  parseOtoolInstallNames,
  verifyNativeRoots,
} from './verify-native-architecture.mjs';

test('parses thin and fat lipo output', () => {
  assert.deepEqual(parseLipoArchitectures('x86_64\n'), ['x86_64']);
  assert.deepEqual(
    parseLipoArchitectures('Architectures in the fat file: app are: x86_64 arm64\n'),
    ['x86_64', 'arm64'],
  );
});

test('parses linked dylibraries from otool output', () => {
  assert.deepEqual(
    parseOtoolDependencies('app:\n\t@rpath/libok.dylib (compatibility version 1.0.0, current version 1.0.0)\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n'),
    ['@rpath/libok.dylib', '/usr/lib/libSystem.B.dylib'],
  );
});

test('ignores per-architecture headers in universal otool output', () => {
  assert.deepEqual(
    parseOtoolDependencies('binary (architecture x86_64):\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\nbinary (architecture arm64):\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)\n'),
    ['/usr/lib/libSystem.B.dylib', '/usr/lib/libSystem.B.dylib'],
  );
});

test('parses dylib install names without architecture headers', () => {
  assert.deepEqual(
    parseOtoolInstallNames('binary:\n/DLC/package/libnative.dylib\n'),
    ['/DLC/package/libnative.dylib'],
  );
});

test('ignores a dylib install name when auditing absolute dependencies', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xpdite-native-id-'));
  fs.writeFileSync(path.join(root, 'binary'), 'placeholder');

  const result = verifyNativeRoots({
    roots: [root],
    architecture: 'arm64',
    tools: {
      file: () => 'Mach-O 64-bit dynamically linked shared library arm64',
      lipo: () => 'arm64',
      otool: () => 'binary:\n\t/DLC/package/libnative.dylib (compatibility version 1.0.0, current version 1.0.0)',
      otoolInstallNames: () => 'binary:\n/DLC/package/libnative.dylib',
    },
  });

  assert.equal(result.scannedCount, 1);
});

test('accepts universal files containing the target slice', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xpdite-native-ok-'));
  const binary = path.join(root, 'binary');
  fs.writeFileSync(binary, 'placeholder');

  const result = verifyNativeRoots({
    roots: [root],
    architecture: 'x64',
    tools: {
      file: () => 'Mach-O universal binary',
      lipo: () => 'x86_64 arm64',
      otool: () => 'binary:\n\t@rpath/libportaudio.dylib (compatibility version 1.0.0, current version 1.0.0)',
    },
  });

  assert.equal(result.scannedCount, 1);
});

test('rejects wrong slices and Homebrew-linked dependencies', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xpdite-native-bad-'));
  fs.writeFileSync(path.join(root, 'binary'), 'placeholder');

  assert.throws(
    () => verifyNativeRoots({
      roots: [root],
      architecture: 'x64',
      tools: {
        file: () => 'Mach-O 64-bit executable arm64',
        lipo: () => 'arm64',
        otool: () => 'binary:\n\t/opt/homebrew/lib/libportaudio.dylib (compatibility version 1.0.0, current version 1.0.0)',
      },
    }),
    /expected x86_64[\s\S]*build-host-only dependency/,
  );
});

test('post-package scan rejects build cache metadata', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xpdite-native-stamp-'));
  fs.writeFileSync(path.join(root, '.build-stamp.json'), '{}');
  fs.writeFileSync(path.join(root, 'binary'), 'placeholder');

  assert.throws(
    () => verifyNativeRoots({
      roots: [root],
      architecture: 'arm64',
      rejectBuildMetadata: true,
      tools: {
        file: () => 'Mach-O 64-bit executable arm64',
        lipo: () => 'arm64',
        otool: () => 'binary:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)',
      },
    }),
    /build cache metadata must not be packaged/,
  );
});
