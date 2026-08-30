import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { resolveBuildProfileFromEnvironment } from './build-profile.mjs';

const projectRoot = process.cwd();
const outputDir = path.join(projectRoot, 'dist-python-runtime');
const stampPath = path.join(outputDir, '.build-stamp.json');
const copiedSourceTargets = ['source', 'mcp_servers'];
const resolvedProfile = resolveBuildProfileFromEnvironment(process.env, { projectRoot });

const ignoredDirectoryNames = new Set([
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
  '.git',
]);
const buildOnlyPackageNames = new Set([
  'PyInstaller',
  '_pytest',
  'altgraph',
  'macholib',
  'pytest',
  'pytest_asyncio',
  'ruff',
]);
const buildOnlyMetadataPrefixes = [
  'altgraph-',
  'macholib-',
  'pyinstaller-',
  'pyinstaller_hooks_contrib-',
  'pytest-',
  'pytest_asyncio-',
  'ruff-',
];
const macSystemDependencyPrefixes = ['/usr/lib/', '/System/Library/'];
const machOMagics = new Set([
  'cafebabe',
  'cafebabf',
  'cefaedfe',
  'cffaedfe',
  'feedface',
  'feedfacf',
  'bebafeca',
  'bfbafeca',
]);

function shouldCopy(srcPath) {
  const baseName = path.basename(srcPath);

  if (ignoredDirectoryNames.has(baseName)) {
    return false;
  }

  if (
    buildOnlyPackageNames.has(baseName)
    || buildOnlyMetadataPrefixes.some((prefix) => baseName.startsWith(prefix))
  ) {
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
  const configuredEnvironment = process.env.XPDITE_PYTHON_ENV?.trim();
  const candidates = process.platform === 'win32'
    ? [
        ...(configuredEnvironment
          ? [path.join(configuredEnvironment, 'Scripts', 'python.exe')]
          : []),
        path.join(projectRoot, '.venv', 'Scripts', 'python.exe'),
        path.join(projectRoot, '.venv', 'Scripts', 'python'),
      ]
    : [
        ...(configuredEnvironment
          ? [
              path.join(configuredEnvironment, 'bin', 'python3'),
              path.join(configuredEnvironment, 'bin', 'python'),
            ]
          : []),
        path.join(projectRoot, '.venv', 'bin', 'python3'),
        path.join(projectRoot, '.venv', 'bin', 'python'),
      ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    'Bundled runtime build requires a synchronized profile. Run "bun run install:python" first.',
  );
}

function readRuntimeInfo(pythonExecutable) {
  const helperScript = [
    'import json',
    'import pathlib',
    'import sys',
    'import sysconfig',
    'import platform',
    'info = {',
    "  'executable': str(pathlib.Path(sys.executable).resolve()),",
    "  'base_prefix': str(pathlib.Path(sys.base_prefix).resolve()),",
    "  'site_packages': str(pathlib.Path(sysconfig.get_path('purelib')).resolve()),",
    "  'platform': sys.platform,",
    "  'version_major_minor': f'{sys.version_info.major}.{sys.version_info.minor}',",
    "  'machine': platform.machine(),",
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
    executable: parsed.executable,
    sitePackages: parsed.site_packages,
    platform: parsed.platform,
    versionMajorMinor: parsed.version_major_minor,
    machine: parsed.machine,
  };
}

function resolveSitePackagesRelativePath(runtimeInfo) {
  if (runtimeInfo.platform === 'win32') {
    return path.join('Lib', 'site-packages');
  }

  return path.join('lib', `python${runtimeInfo.versionMajorMinor}`, 'site-packages');
}

function buildStamp(runtimeInfo, sitePackagesRelativePath) {
  const basePrefixPath = path.join(resolvedProfile.environmentDir, 'pyvenv.cfg');
  const lockfilePath = path.join(projectRoot, 'uv.lock');
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
    ...['scripts/build-python-runtime.mjs', 'pyproject.toml', 'uv.lock'].map((relativePath) => ({
      kind: 'build-config',
      path: relativePath,
      ...collectInputState(path.join(projectRoot, relativePath)),
    })),
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
    schemaVersion: 3,
    target: {
      platform: resolvedProfile.platform,
      architecture: resolvedProfile.architecture,
      profile: resolvedProfile.profile,
      groups: resolvedProfile.groups,
    },
    lockfileSha256: crypto
      .createHash('sha256')
      .update(fs.readFileSync(lockfilePath))
      .digest('hex'),
    python: {
      executable: runtimeInfo.executable,
      basePrefix: runtimeInfo.basePrefix,
      sitePackages: runtimeInfo.sitePackages,
      sitePackagesRelativePath,
      platform: runtimeInfo.platform,
      versionMajorMinor: runtimeInfo.versionMajorMinor,
      machine: runtimeInfo.machine,
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

  const macNativeResourcesExist = resolvedProfile.platform !== 'darwin'
    || (
      fs.existsSync(path.join(runtimeRoot, 'lib', 'xpdite-native'))
      && fs.readdirSync(path.join(runtimeRoot, 'lib', 'xpdite-native'))
        .some((entry) => entry.includes('libportaudio') && entry.endsWith('.dylib'))
    );

  return (
    fs.existsSync(runtimeRoot)
    && fs.existsSync(runtimeExecutable)
    && fs.existsSync(path.join(runtimeRoot, sitePackagesRelativePath))
    && copiedSourceTargets.every((relativePath) => (
      fs.existsSync(path.join(outputDir, relativePath))
    ))
    && macNativeResourcesExist
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

function runTool(command, args) {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    encoding: 'utf8',
    shell: false,
  });
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(' ')} failed.\nSTDOUT:\n${result.stdout}\nSTDERR:\n${result.stderr}`,
    );
  }
  return result.stdout;
}

function findFiles(root, predicate) {
  const matches = [];
  const stack = fs.existsSync(root) ? [root] : [];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current) continue;
    const stats = fs.lstatSync(current);
    if (stats.isSymbolicLink()) continue;
    if (stats.isFile()) {
      if (predicate(current)) matches.push(current);
      continue;
    }
    if (stats.isDirectory()) {
      for (const entry of fs.readdirSync(current)) stack.push(path.join(current, entry));
    }
  }
  return matches;
}

function isMachOFile(filePath) {
  const descriptor = fs.openSync(filePath, 'r');
  try {
    const magic = Buffer.allocUnsafe(4);
    return fs.readSync(descriptor, magic, 0, magic.length, 0) === magic.length
      && machOMagics.has(magic.toString('hex'));
  } finally {
    fs.closeSync(descriptor);
  }
}

function parseOtoolEntries(output) {
  return output
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.endsWith(':'))
    .map((line) => line.split(/\s+\(/, 1)[0]);
}

function readInstallNames(filePath) {
  return parseOtoolEntries(runTool('/usr/bin/otool', ['-m', '-D', filePath]));
}

function packagedLoaderReference(fromPath, toPath) {
  const relativePath = path.relative(path.dirname(fromPath), toPath).split(path.sep).join('/');
  return `@loader_path/${relativePath}`;
}

function bundleMacRuntimeDependencies(runtimeTargetRoot, runtimeInfo, sitePackagesTarget) {
  if (resolvedProfile.platform !== 'darwin') return;

  const nativeLibraryDir = path.join(runtimeTargetRoot, 'lib', 'xpdite-native');
  fs.mkdirSync(nativeLibraryDir, { recursive: true });
  const initialFiles = findFiles(runtimeTargetRoot, isMachOFile);
  const installNameTargets = new Map();
  for (const filePath of initialFiles) {
    for (const installName of readInstallNames(filePath)) {
      installNameTargets.set(installName, filePath);
    }
  }

  const resolvedBasePrefix = fs.realpathSync(runtimeInfo.basePrefix);
  const resolvedSitePackages = fs.realpathSync(runtimeInfo.sitePackages);
  const queued = [...initialFiles];
  const processed = new Set();
  const copiedExternalLibraries = new Map();
  let rewrittenDependencies = 0;

  function copyExternalLibrary(sourcePath) {
    const resolvedSource = fs.realpathSync(sourcePath);
    const existing = copiedExternalLibraries.get(resolvedSource);
    if (existing) return existing;

    const sourceHash = crypto.createHash('sha256').update(resolvedSource).digest('hex').slice(0, 12);
    const destination = path.join(nativeLibraryDir, `${sourceHash}-${path.basename(resolvedSource)}`);
    fs.copyFileSync(resolvedSource, destination);
    copiedExternalLibraries.set(resolvedSource, destination);
    queued.push(destination);
    for (const installName of readInstallNames(destination)) {
      installNameTargets.set(installName, destination);
    }
    return destination;
  }

  function resolvePackagedTarget(dependency) {
    const knownTarget = installNameTargets.get(dependency);
    if (knownTarget) return knownTarget;

    if (!fs.existsSync(dependency)) {
      throw new Error(`Unresolved build-host dynamic library dependency: ${dependency}`);
    }
    const resolvedDependency = fs.realpathSync(dependency);
    if (
      resolvedDependency === resolvedBasePrefix
      || resolvedDependency.startsWith(`${resolvedBasePrefix}${path.sep}`)
    ) {
      const target = path.join(
        runtimeTargetRoot,
        path.relative(resolvedBasePrefix, resolvedDependency),
      );
      if (!fs.existsSync(target)) {
        throw new Error(`Copied Python runtime is missing dependency target: ${target}`);
      }
      return target;
    }
    if (
      resolvedDependency === resolvedSitePackages
      || resolvedDependency.startsWith(`${resolvedSitePackages}${path.sep}`)
    ) {
      const target = path.join(
        sitePackagesTarget,
        path.relative(resolvedSitePackages, resolvedDependency),
      );
      if (!fs.existsSync(target)) {
        throw new Error(`Copied site-packages tree is missing dependency target: ${target}`);
      }
      return target;
    }
    if (
      resolvedDependency === runtimeTargetRoot
      || resolvedDependency.startsWith(`${runtimeTargetRoot}${path.sep}`)
    ) {
      return resolvedDependency;
    }
    return copyExternalLibrary(resolvedDependency);
  }

  while (queued.length > 0) {
    const binary = queued.pop();
    if (!binary || processed.has(binary)) continue;
    processed.add(binary);
    const installNames = new Set(readInstallNames(binary));
    const dependencies = parseOtoolEntries(runTool('/usr/bin/otool', ['-m', '-L', binary]));
    let changed = false;

    for (const dependency of dependencies) {
      if (
        installNames.has(dependency)
        || dependency.startsWith('@')
        || macSystemDependencyPrefixes.some((prefix) => dependency.startsWith(prefix))
      ) {
        continue;
      }
      if (!path.isAbsolute(dependency)) continue;

      const packagedTarget = resolvePackagedTarget(dependency);
      fs.chmodSync(binary, fs.statSync(binary).mode | 0o200);
      runTool('/usr/bin/install_name_tool', [
        '-change',
        dependency,
        packagedLoaderReference(binary, packagedTarget),
        binary,
      ]);
      changed = true;
      rewrittenDependencies += 1;
    }

    if (installNames.size > 0) {
      const installName = `@rpath/${path.basename(binary)}`;
      if (![...installNames].every((value) => value === installName)) {
        fs.chmodSync(binary, fs.statSync(binary).mode | 0o200);
        runTool('/usr/bin/install_name_tool', ['-id', installName, binary]);
        changed = true;
      }
    }

    if (changed && !isMachOFile(binary)) {
      throw new Error(`Relocating native dependencies corrupted Mach-O file: ${binary}`);
    }
    if (changed) {
      runTool('/usr/bin/codesign', ['--force', '--sign', '-', binary]);
    }
  }

  console.log(
    `Relocated ${rewrittenDependencies} macOS runtime dependencies and bundled `
    + `${copiedExternalLibraries.size} external libraries.`,
  );
}

function bundleMacPortAudio(sitePackagesTarget, runtimeTargetRoot) {
  if (resolvedProfile.platform !== 'darwin') return;

  const extensions = findFiles(
    sitePackagesTarget,
    (filePath) => path.basename(filePath).startsWith('_portaudio') && filePath.endsWith('.so'),
  );
  if (extensions.length === 0) {
    throw new Error(
      `Missing PyAudio native extension for profile ${resolvedProfile.profile}. ` +
      'Install PortAudio and synchronize the transcription dependency group.',
    );
  }

  const runtimeLibraryDir = path.join(runtimeTargetRoot, 'lib', 'xpdite-native');
  fs.mkdirSync(runtimeLibraryDir, { recursive: true });
  let bundledDependencies = 0;

  for (const extension of extensions) {
    const dependencyLines = runTool('/usr/bin/otool', ['-m', '-L', extension]).split(/\r?\n/);
    const portAudioReference = dependencyLines
      .map((line) => line.trim().split(/\s+\(/, 1)[0])
      .find((dependency) => dependency.toLowerCase().includes('libportaudio'));
    if (!portAudioReference) {
      throw new Error(`PyAudio extension does not declare a PortAudio library: ${extension}`);
    }

    let sourceLibrary = portAudioReference;
    if (!path.isAbsolute(sourceLibrary) || !fs.existsSync(sourceLibrary)) {
      const brewPrefix = runTool('brew', ['--prefix', 'portaudio']).trim();
      const candidates = findFiles(
        path.join(brewPrefix, 'lib'),
        (filePath) => /^libportaudio(?:\.\d+)*\.dylib$/.test(path.basename(filePath)),
      );
      sourceLibrary = candidates[0] || '';
    }
    if (!sourceLibrary || !fs.existsSync(sourceLibrary)) {
      throw new Error(
        'PortAudio build dependency could not be located. Run `brew install portaudio`.',
      );
    }

    const destinationLibrary = path.join(runtimeLibraryDir, path.basename(sourceLibrary));
    fs.copyFileSync(fs.realpathSync(sourceLibrary), destinationLibrary);
    runTool('/usr/bin/install_name_tool', [
      '-id',
      `@rpath/${path.basename(destinationLibrary)}`,
      destinationLibrary,
    ]);
    const relativeLibrary = path.relative(path.dirname(extension), destinationLibrary);
    const packagedReference = `@loader_path/${relativeLibrary.split(path.sep).join('/')}`;
    runTool('/usr/bin/install_name_tool', [
      '-change',
      portAudioReference,
      packagedReference,
      extension,
    ]);
    runTool('/usr/bin/codesign', ['--force', '--sign', '-', extension]);
    runTool('/usr/bin/codesign', ['--force', '--sign', '-', destinationLibrary]);
    bundledDependencies += 1;
  }

  if (bundledDependencies === 0) {
    throw new Error('PortAudio was not bundled into the standalone Python runtime.');
  }
  console.log(`Bundled PortAudio for ${bundledDependencies} PyAudio extension(s).`);
}

const pythonExecutable = resolveBuildPythonExecutable();
const runtimeInfo = readRuntimeInfo(pythonExecutable);
const expectedMachine = resolvedProfile.architecture === 'x64' ? 'x86_64' : 'arm64';
const normalizedMachine = runtimeInfo.machine === 'AMD64' ? 'x86_64' : runtimeInfo.machine;
if (normalizedMachine !== expectedMachine) {
  throw new Error(
    `Wrong Python architecture for ${resolvedProfile.profile}: ` +
    `expected ${expectedMachine}, found ${runtimeInfo.machine}.`,
  );
}
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
bundleMacPortAudio(sitePackagesTarget, runtimeTargetRoot);
bundleMacRuntimeDependencies(runtimeTargetRoot, runtimeInfo, sitePackagesTarget);

for (const relativePath of copiedSourceTargets) {
  const sourcePath = path.join(projectRoot, relativePath);
  const targetPath = path.join(outputDir, relativePath);
  copyTree(sourcePath, targetPath);
}

fs.writeFileSync(stampPath, JSON.stringify(currentStamp, null, 2));
console.log(`Bundled standalone Python runtime resources at ${outputDir}`);
