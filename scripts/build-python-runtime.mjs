import fs from 'node:fs';
import path from 'node:path';

const projectRoot = process.cwd();
const outputDir = path.join(projectRoot, 'dist-python-runtime');
const stampPath = path.join(outputDir, '.build-stamp.json');
const copyTargets = [
  '.venv',
  'source',
  'mcp_servers',
];

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

    if (!stats.isDirectory()) {
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

function buildStamp() {
  return {
    version: 1,
    targets: copyTargets.map((relativePath) => {
      const sourcePath = path.join(projectRoot, relativePath);
      if (!fs.existsSync(sourcePath)) {
        throw new Error(`Required runtime resource missing: ${sourcePath}`);
      }

      return {
        relativePath,
        ...collectInputState(sourcePath),
      };
    }),
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

function outputsExist() {
  return copyTargets.every((relativePath) => (
    fs.existsSync(path.join(outputDir, relativePath))
  ));
}

const currentStamp = buildStamp();
const previousStamp = readExistingStamp();

if (
  previousStamp
  && JSON.stringify(previousStamp) === JSON.stringify(currentStamp)
  && outputsExist()
) {
  console.log(`Bundled Python runtime resources are up to date at ${outputDir}`);
  process.exit(0);
}

fs.rmSync(outputDir, { recursive: true, force: true });
fs.mkdirSync(outputDir, { recursive: true });

for (const relativePath of copyTargets) {
  const sourcePath = path.join(projectRoot, relativePath);
  const targetPath = path.join(outputDir, relativePath);
  fs.cpSync(sourcePath, targetPath, {
    recursive: true,
    filter: shouldCopy,
  });
}

fs.writeFileSync(stampPath, JSON.stringify(currentStamp, null, 2));
console.log(`Bundled Python runtime resources at ${outputDir}`);
