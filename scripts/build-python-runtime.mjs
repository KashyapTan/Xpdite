import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const projectRoot = process.cwd();
const outputDir = path.join(projectRoot, 'dist-python-runtime');
const stampPath = path.join(outputDir, '.build-stamp.json');
const copiedSourceTargets = ['source', 'mcp_servers'];

const ignoredDirectoryNames = new Set([
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  '.git',
]);

function shouldCopy(srcPath) {
  const baseName = path.basename(srcPath);

  if (ignoredDirectoryNames.has(baseName)) {
    return false;
  }

  if (baseName.endsWith('.pyc') || baseName.endsWith('.pyo')) {
    return false;
  }

  return true;
}

function collectInputState(sourcePath) {
  const stack = [sourcePath];
  let latestMtimeMs = 0;
  let entryCount = 0;

  while (stack.length > 0) {
    const currentPath = stack.pop();
    if (!currentPath || !shouldCopy(currentPath)) {
      continue;
    }

    const stats = fs.lstatSync(currentPath);
    latestMtimeMs = Math.max(latestMtimeMs, stats.mtimeMs);
    entryCount += 1;

    if (!stats.isDirectory() || stats.isSymbolicLink()) {
      continue;
    }

    const children = fs.readdirSync(currentPath);
    for (const child of children) {
      stack.push(path.join(currentPath, child));
    }
  }

  return {
    latestMtimeMs,
    entryCount,
  };
}

function resolveBuildPythonExecutable() {
  const candidates = process.platform === 'win32'
    ? [
        path.join(projectRoot, '.venv', 'Scripts', 'python.exe'),
        path.join(projectRoot, '.venv', 'Scripts', 'python'),
      ]
    : [
        path.join(projectRoot, '.venv', 'bin', 'python3'),
        path.join(projectRoot, '.venv', 'bin', 'python'),
      ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    'Bundled runtime build requires a project virtualenv. Run "uv sync --group dev" first.',
  );
}

function readRuntimeInfo(pythonExecutable) {
  const helperScript = [
    'import json',
    'import pathlib',
    'import sys',
    'import sysconfig',
    'info = {',
    "  'base_prefix': str(pathlib.Path(sys.base_prefix).resolve()),",
    "  'site_packages': str(pathlib.Path(sysconfig.get_path('purelib')).resolve()),",
    "  'platform': sys.platform,",
    "  'version_major_minor': f'{sys.version_info.major}.{sys.version_info.minor}',",
    '}',
    'print(json.dumps(info))',
  ].join('\n');

  const result = spawnSync(pythonExecutable, ['-c', helperScript], {
    cwd: projectRoot,
    encoding: 'utf8',
    shell: false,
  });

  if (result.status !== 0) {
    throw new Error(
      `Failed to inspect Python runtime.\nSTDOUT:\n${result.stdout}\nSTDERR:\n${result.stderr}`,
    );
  }

  const parsed = JSON.parse(result.stdout.trim());
  if (!parsed.base_prefix || !parsed.site_packages || !parsed.version_major_minor) {
    throw new Error(`Incomplete Python runtime metadata: ${result.stdout}`);
  }

  return {
    basePrefix: parsed.base_prefix,
    sitePackages: parsed.site_packages,
    platform: parsed.platform,
    versionMajorMinor: parsed.version_major_minor,
  };
}

function resolveSitePackagesRelativePath(runtimeInfo) {
  if (runtimeInfo.platform === 'win32') {
    return path.join('Lib', 'site-packages');
  }

  return path.join('lib', `python${runtimeInfo.versionMajorMinor}`, 'site-packages');
}

function buildStamp(runtimeInfo, sitePackagesRelativePath) {
  const basePrefixPath = path.join(projectRoot, '.venv', 'pyvenv.cfg');
  const trackedPaths = [
    {
      kind: 'base-runtime',
      path: runtimeInfo.basePrefix,
      ...collectInputState(runtimeInfo.basePrefix),
    },
    {
      kind: 'site-packages',
      path: runtimeInfo.sitePackages,
      ...collectInputState(runtimeInfo.sitePackages),
    },
    ...(fs.existsSync(basePrefixPath)
      ? [
          {
            kind: 'venv-config',
            path: basePrefixPath,
            ...collectInputState(basePrefixPath),
          },
        ]
      : []),
    ...copiedSourceTargets.map((relativePath) => {
      const sourcePath = path.join(projectRoot, relativePath);
      if (!fs.existsSync(sourcePath)) {
        throw new Error(`Required runtime resource missing: ${sourcePath}`);
      }

      return {
        kind: 'source',
        path: relativePath,
        ...collectInputState(sourcePath),
      };
    }),
  ];

  return {
    version: 2,
    python: {
      basePrefix: runtimeInfo.basePrefix,
      sitePackages: runtimeInfo.sitePackages,
      sitePackagesRelativePath,
      platform: runtimeInfo.platform,
      versionMajorMinor: runtimeInfo.versionMajorMinor,
    },
    trackedPaths,
  };
}

function readExistingStamp() {
  if (!fs.existsSync(stampPath)) {
    return null;
  }

  try {
    return JSON.parse(fs.readFileSync(stampPath, 'utf8'));
  } catch {
    return null;
  }
}

function outputsExist(sitePackagesRelativePath) {
  const runtimeRoot = path.join(outputDir, 'python');
  const runtimeExecutable = process.platform === 'win32'
    ? path.join(runtimeRoot, 'python.exe')
    : path.join(runtimeRoot, 'bin', 'python3');

  return (
    fs.existsSync(runtimeRoot)
    && fs.existsSync(runtimeExecutable)
    && fs.existsSync(path.join(runtimeRoot, sitePackagesRelativePath))
    && copiedSourceTargets.every((relativePath) => (
      fs.existsSync(path.join(outputDir, relativePath))
    ))
  );
}

function copyTree(sourcePath, targetPath) {
  fs.cpSync(sourcePath, targetPath, {
    recursive: true,
    dereference: true,
    filter: shouldCopy,
    force: true,
  });
}

const pythonExecutable = resolveBuildPythonExecutable();
const runtimeInfo = readRuntimeInfo(pythonExecutable);
const sitePackagesRelativePath = resolveSitePackagesRelativePath(runtimeInfo);
const currentStamp = buildStamp(runtimeInfo, sitePackagesRelativePath);
const previousStamp = readExistingStamp();

if (
  previousStamp
  && JSON.stringify(previousStamp) === JSON.stringify(currentStamp)
  && outputsExist(sitePackagesRelativePath)
) {
  console.log(`Bundled Python runtime resources are up to date at ${outputDir}`);
  process.exit(0);
}

const runtimeTargetRoot = path.join(outputDir, 'python');
const sitePackagesTarget = path.join(runtimeTargetRoot, sitePackagesRelativePath);

fs.rmSync(outputDir, { recursive: true, force: true });
fs.mkdirSync(outputDir, { recursive: true });

copyTree(runtimeInfo.basePrefix, runtimeTargetRoot);
fs.mkdirSync(sitePackagesTarget, { recursive: true });
copyTree(runtimeInfo.sitePackages, sitePackagesTarget);

for (const relativePath of copiedSourceTargets) {
  const sourcePath = path.join(projectRoot, relativePath);
  const targetPath = path.join(outputDir, relativePath);
  copyTree(sourcePath, targetPath);
}

fs.writeFileSync(stampPath, JSON.stringify(currentStamp, null, 2));
console.log(`Bundled standalone Python runtime resources at ${outputDir}`);
