import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const EXPECTED_MACH_ARCH = {
  arm64: 'arm64',
  x64: 'x86_64',
};

const SYSTEM_DEPENDENCY_PREFIXES = ['/usr/lib/', '/System/Library/'];
const MACH_O_MAGICS = new Set([
  'cafebabe',
  'cafebabf',
  'cefaedfe',
  'cffaedfe',
  'feedface',
  'feedfacf',
  'bebafeca',
  'bfbafeca',
]);

export function isMachODescription(description) {
  return description.includes('Mach-O');
}

export function parseLipoArchitectures(output) {
  const trimmed = output.trim();
  if (!trimmed) return [];
  const marker = trimmed.includes(':') ? trimmed.slice(trimmed.lastIndexOf(':') + 1) : trimmed;
  return marker.trim().split(/\s+/).filter(Boolean);
}

export function parseOtoolDependencies(output) {
  return output
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.endsWith(':'))
    .map((line) => line.split(/\s+\(/, 1)[0])
    .filter(Boolean);
}

export function parseOtoolInstallNames(output) {
  return output
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.endsWith(':'));
}

function hasMachOMagic(filePath) {
  const descriptor = fs.openSync(filePath, 'r');
  try {
    const magic = Buffer.allocUnsafe(4);
    return fs.readSync(descriptor, magic, 0, magic.length, 0) === magic.length
      && MACH_O_MAGICS.has(magic.toString('hex'));
  } finally {
    fs.closeSync(descriptor);
  }
}

function runTool(command, args) {
  const result = spawnSync(command, args, {
    encoding: 'utf8',
    shell: false,
  });
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(' ')} failed: ${(result.stderr || result.stdout || '').trim()}`,
    );
  }
  return result.stdout;
}

function collectFiles(root) {
  if (!fs.existsSync(root)) {
    throw new Error(`Native architecture scan root does not exist: ${root}`);
  }
  const files = [];
  const stack = [root];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current) continue;
    const stats = fs.lstatSync(current);
    if (stats.isSymbolicLink()) continue;
    if (stats.isFile()) {
      files.push(current);
      continue;
    }
    if (stats.isDirectory()) {
      for (const entry of fs.readdirSync(current)) {
        stack.push(path.join(current, entry));
      }
    }
  }
  return files;
}

export function verifyNativeRoots({ roots, architecture, tools = {}, rejectBuildMetadata = false }) {
  const expectedArchitecture = EXPECTED_MACH_ARCH[architecture];
  if (!expectedArchitecture) {
    throw new Error(`Unsupported Mach-O target architecture: ${architecture}`);
  }

  const isMachO = tools.file
    ? ((filePath) => isMachODescription(tools.file(filePath)))
    : hasMachOMagic;
  const lipoTool = tools.lipo || ((filePath) => runTool('/usr/bin/lipo', ['-archs', filePath]));
  const otool = tools.otool || ((filePath) => runTool('/usr/bin/otool', ['-m', '-L', filePath]));
  const otoolInstallNames = tools.otoolInstallNames
    || (tools.otool
      ? (() => '')
      : ((filePath) => runTool('/usr/bin/otool', ['-m', '-D', filePath])));
  const scanned = [];
  const failures = [];

  for (const root of roots) {
    for (const filePath of collectFiles(path.resolve(root))) {
      if (rejectBuildMetadata && path.basename(filePath) === '.build-stamp.json') {
        failures.push(`${filePath}: build cache metadata must not be packaged`);
        continue;
      }
      if (!isMachO(filePath)) continue;

      scanned.push(filePath);
      const architectures = parseLipoArchitectures(lipoTool(filePath));
      if (!architectures.includes(expectedArchitecture)) {
        failures.push(
          `${filePath}: expected ${expectedArchitecture}, found ${architectures.join(', ') || 'unknown'}`,
        );
      }

      const installNames = new Set(parseOtoolInstallNames(otoolInstallNames(filePath)));
      for (const dependency of parseOtoolDependencies(otool(filePath))) {
        if (installNames.has(dependency)) continue;
        if (
          dependency.startsWith('/')
          && !SYSTEM_DEPENDENCY_PREFIXES.some((prefix) => dependency.startsWith(prefix))
        ) {
          failures.push(`${filePath}: build-host-only dependency ${dependency}`);
        }
      }
    }
  }

  if (failures.length > 0) {
    throw new Error(`Native architecture validation failed:\n${failures.join('\n')}`);
  }
  if (scanned.length === 0) {
    throw new Error(`Native architecture validation found no Mach-O files under: ${roots.join(', ')}`);
  }

  return { scannedCount: scanned.length, expectedArchitecture };
}

function cliArgumentValues(name) {
  const values = [];
  for (let index = 2; index < process.argv.length; index += 1) {
    if (process.argv[index] === name && process.argv[index + 1]) {
      values.push(process.argv[index + 1]);
      index += 1;
    }
  }
  return values;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const architecture = cliArgumentValues('--arch')[0];
  const roots = cliArgumentValues('--root');
  if (!architecture || roots.length === 0) {
    throw new Error(
      'Usage: node scripts/verify-native-architecture.mjs --arch <arm64|x64> --root <path> [--root <path>]',
    );
  }
  const result = verifyNativeRoots({ roots, architecture });
  console.log(
    `Validated ${result.scannedCount} Mach-O files for ${result.expectedArchitecture}.`,
  );
}
