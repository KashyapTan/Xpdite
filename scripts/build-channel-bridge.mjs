import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const distDir = path.join(projectRoot, 'dist-channel-bridge');
const bundlePath = path.join(distDir, 'index.cjs');
const bundleMapPath = path.join(distDir, 'index.cjs.map');
const validationUserDataDir = path.join(distDir, 'validate-user-data');
const sourceAdjacentBundlePath = path.join(projectRoot, 'src', 'channel-bridge', 'index.cjs');
const sourceAdjacentBundleMapPath = path.join(projectRoot, 'src', 'channel-bridge', 'index.cjs.map');
const mobileRuntimePackages = [
  '@chat-adapter/discord',
  '@chat-adapter/state-memory',
  '@chat-adapter/telegram',
  'baileys',
  'chat',
  'chat-adapter-baileys',
];

function runCommand(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    encoding: 'utf8',
    stdio: 'pipe',
    ...options,
  });

  if (result.stdout) {
    process.stdout.write(result.stdout);
  }

  if (result.stderr) {
    process.stderr.write(result.stderr);
  }

  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} failed with exit code ${result.status ?? 'unknown'}`);
  }
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function verifyBundleOutput() {
  if (!existsSync(bundlePath)) {
    throw new Error(`Channel bridge bundle was not created at ${bundlePath}`);
  }

  const bundleSource = readFileSync(bundlePath, 'utf8');
  const unresolvedPackages = mobileRuntimePackages.filter((specifier) => {
    const requirePattern = new RegExp(`require\\((['"])${escapeRegExp(specifier)}\\1\\)`);
    const dynamicImportPattern = new RegExp(`import\\((['"])${escapeRegExp(specifier)}\\1\\)`);
    const fromPattern = new RegExp(`from\\s+(['"])${escapeRegExp(specifier)}\\1`);
    return requirePattern.test(bundleSource)
      || dynamicImportPattern.test(bundleSource)
      || fromPattern.test(bundleSource);
  });

  if (unresolvedPackages.length > 0) {
    throw new Error(
      `Channel bridge bundle still contains unresolved runtime package imports: ${unresolvedPackages.join(', ')}`,
    );
  }
}

function moveUnexpectedBunOutputsIntoDist() {
  if (!existsSync(bundlePath) && existsSync(sourceAdjacentBundlePath)) {
    renameSync(sourceAdjacentBundlePath, bundlePath);
  }

  if (!existsSync(bundleMapPath) && existsSync(sourceAdjacentBundleMapPath)) {
    renameSync(sourceAdjacentBundleMapPath, bundleMapPath);
  }
}

function validateBundleRuntime() {
  rmSync(validationUserDataDir, { force: true, recursive: true });
  mkdirSync(validationUserDataDir, { recursive: true });

  try {
    runCommand(process.execPath, [bundlePath], {
      env: {
        ...process.env,
        XPDITE_CHANNEL_BRIDGE_VALIDATE_ONLY: '1',
        XPDITE_USER_DATA_DIR: validationUserDataDir,
        PYTHON_SERVER_PORT: '8000',
        BRIDGE_PORT: '9000',
      },
    });
  } finally {
    rmSync(validationUserDataDir, { force: true, recursive: true });
  }
}

rmSync(distDir, { force: true, recursive: true });
mkdirSync(distDir, { recursive: true });
rmSync(sourceAdjacentBundlePath, { force: true });
rmSync(sourceAdjacentBundleMapPath, { force: true });

runCommand('bun', [
  'build',
  './src/channel-bridge/index.ts',
  '--outdir',
  './dist-channel-bridge',
  '--target=node',
  '--format=cjs',
  '--packages=bundle',
  '--entry-naming',
  'index.cjs',
  '--sourcemap=external',
]);

moveUnexpectedBunOutputsIntoDist();
verifyBundleOutput();
validateBundleRuntime();

console.log(`Built self-contained channel bridge bundle at ${bundlePath}`);
