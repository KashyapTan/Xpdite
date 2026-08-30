import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  assertNativeHost,
  buildProfileEnvironment,
  pythonSyncArguments,
  resolveBuildProfile,
} from './build-profile.mjs';

function argumentValue(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? undefined : process.argv[index + 1];
}

const resolved = resolveBuildProfile({
  platform: argumentValue('--platform') || process.platform,
  architecture: argumentValue('--arch') || process.arch,
  profile: argumentValue('--profile'),
});
assertNativeHost(resolved);

const environment = buildProfileEnvironment(resolved);
console.log(`Python target: ${resolved.platform}/${resolved.architecture}`);
console.log(`Build profile: ${resolved.profile}`);
console.log(`Dependency groups: ${resolved.groups.join(', ')}`);
console.log(`Environment: ${resolved.environmentDir}`);

const syncArgs = pythonSyncArguments(resolved);
const result = spawnSync('uv', syncArgs, {
  cwd: process.cwd(),
  env: environment,
  stdio: 'inherit',
  shell: false,
});
if (result.status !== 0) {
  throw new Error(`uv ${syncArgs.join(' ')} failed with exit code ${result.status ?? 1}`);
}

const pythonExecutable = process.platform === 'win32'
  ? path.join(resolved.environmentDir, 'Scripts', 'python.exe')
  : path.join(resolved.environmentDir, 'bin', 'python');
if (!fs.existsSync(pythonExecutable)) {
  throw new Error(`Python environment was synchronized but no interpreter exists at ${pythonExecutable}`);
}
console.log(`Python executable: ${pythonExecutable}`);
