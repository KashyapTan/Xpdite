import { spawnSync } from 'node:child_process';

const [, , requestedPlatform, requestedArch] = process.argv;
const platform = requestedPlatform?.trim();
const arch = requestedArch?.trim() || 'x64';
const buildVersion = process.env.XPDITE_BUILD_VERSION?.trim();
const macIdentity = process.env.XPDITE_MAC_IDENTITY?.trim();

if (!platform || !['win', 'mac', 'linux'].includes(platform)) {
  throw new Error('Usage: node scripts/run-electron-dist.mjs <win|mac|linux> [arch]');
}

const hostRequirements = {
  win: 'win32',
  mac: 'darwin',
  linux: 'linux',
};

const requiredHost = hostRequirements[platform];
if (process.platform !== requiredHost) {
  throw new Error(
    `dist:${platform} must be run on ${requiredHost}. Current host: ${process.platform}.`,
  );
}

function run(command, args) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    shell: false,
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

run(bunCommand, ['run', 'build']);
run(bunCommand, ['x', 'electron-builder', ...electronBuilderArgs]);
