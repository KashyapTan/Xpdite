import { spawnSync } from 'node:child_process';
import {
  assertNativeHost,
  buildProfileEnvironment,
  resolveBuildProfileFromEnvironment,
} from './build-profile.mjs';

const commandArguments = process.argv.slice(2);
if (commandArguments.length === 0) {
  throw new Error('Usage: node scripts/run-python-profile.mjs <uv run arguments>');
}

const resolved = resolveBuildProfileFromEnvironment();
assertNativeHost(resolved);
const environment = buildProfileEnvironment(resolved);
const uvArguments = ['run', '--no-sync', ...commandArguments];
const result = spawnSync('uv', uvArguments, {
  cwd: process.cwd(),
  env: environment,
  stdio: 'inherit',
  shell: false,
});

if (result.status !== 0) {
  throw new Error(`uv ${uvArguments.join(' ')} failed with exit code ${result.status ?? 1}`);
}
