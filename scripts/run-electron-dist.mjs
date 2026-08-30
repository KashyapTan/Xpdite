import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  assertNativeHost,
  buildProfileEnvironment,
  resolveBuildProfile,
} from './build-profile.mjs';
import { verifyNativeRoots } from './verify-native-architecture.mjs';

const [, , requestedPlatform, requestedArch] = process.argv;
const platform = requestedPlatform?.trim();
const arch = requestedArch?.trim() || 'x64';
const buildVersion = process.env.XPDITE_BUILD_VERSION?.trim();
const macIdentity = process.env.XPDITE_MAC_IDENTITY?.trim();

if (!platform || !['win', 'mac', 'linux'].includes(platform)) {
  throw new Error('Usage: node scripts/run-electron-dist.mjs <win|mac|linux> [arch]');
}

const resolved = resolveBuildProfile({ platform, architecture: arch });
assertNativeHost(resolved);
const buildEnvironment = buildProfileEnvironment(resolved);

console.log(`Distribution target: ${resolved.platform}/${resolved.architecture}`);
console.log(`Build profile: ${resolved.profile}`);
console.log(`Python environment: ${resolved.environmentDir}`);

function run(command, args) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    shell: false,
    env: buildEnvironment,
  });

  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status ?? 1}`);
  }
}

const bunCommand = process.platform === 'win32' ? 'bun.exe' : 'bun';
const electronBuilderArgs = [`--${platform}`, `--${arch}`, '--publish', 'never'];

if (buildVersion) {
  electronBuilderArgs.push(`-c.extraMetadata.version=${buildVersion}`);
}

if (platform === 'mac' && macIdentity) {
  electronBuilderArgs.push(`-c.mac.identity=${macIdentity}`);
}

function findNewestApp(root) {
  const apps = [];
  const stack = fs.existsSync(root) ? [root] : [];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current) continue;
    const stats = fs.lstatSync(current);
    if (!stats.isDirectory()) continue;
    if (current.endsWith('.app')) {
      apps.push({ path: current, mtimeMs: stats.mtimeMs });
      continue;
    }
    for (const entry of fs.readdirSync(current)) {
      stack.push(path.join(current, entry));
    }
  }
  apps.sort((left, right) => right.mtimeMs - left.mtimeMs);
  return apps[0]?.path;
}

run(bunCommand, ['run', 'build']);

if (resolved.platform === 'darwin') {
  const resourceRoots = [
    'dist-python',
    'dist-python-runtime',
    'dist-codex-runtime',
  ].map((entry) => path.resolve(entry));
  const preBuildScan = verifyNativeRoots({
    roots: resourceRoots,
    architecture: resolved.architecture,
  });
  console.log(`Validated ${preBuildScan.scannedCount} native resource files before packaging.`);

  run(bunCommand, ['x', 'electron-builder', ...electronBuilderArgs, '--dir']);
  const appBundle = findNewestApp(path.resolve('dist'));
  if (!appBundle) {
    throw new Error('Electron Builder completed without producing a macOS .app bundle.');
  }
  const appScan = verifyNativeRoots({
    roots: [appBundle],
    architecture: resolved.architecture,
    rejectBuildMetadata: true,
  });
  console.log(`Validated ${appScan.scannedCount} Mach-O files in ${appBundle}.`);
  run(bunCommand, [
    'x',
    'electron-builder',
    ...electronBuilderArgs,
    '--prepackaged',
    appBundle,
  ]);
} else {
  run(bunCommand, ['x', 'electron-builder', ...electronBuilderArgs]);
}
