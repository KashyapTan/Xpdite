import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import sharp from 'sharp';

const projectRoot = process.cwd();
const sourceSvg = path.join(projectRoot, 'assets', 'xpdite-logo-black-bg.svg');
const outputPng = path.join(projectRoot, 'assets', 'xpdite-icon.png');
const outputIco = path.join(projectRoot, 'assets', 'xpdite.ico');
const outputIcns = path.join(projectRoot, 'assets', 'xpdite.icns');
const iconSize = 1024;

function resolvePythonExecutable() {
  const candidates = [
    path.join(projectRoot, '.venv', 'Scripts', 'python.exe'),
    path.join(projectRoot, '.venv', 'bin', 'python'),
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return process.platform === 'win32' ? 'python.exe' : 'python3';
}

if (!fs.existsSync(sourceSvg)) {
  throw new Error(`Missing icon source SVG at ${sourceSvg}`);
}

const renderedPng = await sharp(sourceSvg, { density: iconSize })
  .resize(iconSize, iconSize, {
    fit: 'contain',
    background: { r: 0, g: 0, b: 0, alpha: 1 },
  })
  .flatten({ background: '#000000' })
  .png()
  .toBuffer();

fs.writeFileSync(outputPng, renderedPng);

const pillowScript = `
from PIL import Image

img = Image.open(r"${outputPng.replace(/\\/g, '\\\\')}")
img.save(
    r"${outputIco.replace(/\\/g, '\\\\')}",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
img.save(r"${outputIcns.replace(/\\/g, '\\\\')}")
`;

const pythonResult = spawnSync(resolvePythonExecutable(), ['-c', pillowScript], {
  stdio: 'inherit',
  shell: false,
});

if (pythonResult.status !== 0) {
  throw new Error(`Failed to generate .ico/.icns assets with exit code ${pythonResult.status ?? 1}`);
}

console.log(`Generated packaging icons from ${sourceSvg}`);
