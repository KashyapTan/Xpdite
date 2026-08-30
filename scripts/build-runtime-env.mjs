import fs from 'node:fs';
import path from 'node:path';
import { resolveBuildProfileFromEnvironment } from './build-profile.mjs';

const projectRoot = process.cwd();
const envPath = path.join(projectRoot, '.env');
const outputDir = path.join(projectRoot, 'dist-runtime-config');
const outputPath = path.join(outputDir, 'google-oauth.env');
const capabilitiesPath = path.join(outputDir, 'build-capabilities.json');
const allowlist = ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'];

function parseEnvFile(content) {
  const values = new Map();
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }

    const separatorIndex = line.indexOf('=');
    if (separatorIndex === -1) {
      continue;
    }

    const key = line.slice(0, separatorIndex).trim();
    let value = line.slice(separatorIndex + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    values.set(key, value);
  }
  return values;
}

const parsed = fs.existsSync(envPath)
  ? parseEnvFile(fs.readFileSync(envPath, 'utf8'))
  : new Map();

const resolvedValues = new Map(
  allowlist.map((key) => [key, (process.env[key] ?? parsed.get(key) ?? '').trim()]),
);
const missing = allowlist.filter((key) => !resolvedValues.get(key));
if (missing.length > 0) {
  console.warn(
    `Google OAuth will be unavailable because these optional values are not set: ${missing.join(', ')}`,
  );
}

fs.rmSync(outputDir, { recursive: true, force: true });
fs.mkdirSync(outputDir, { recursive: true });

const serialized = `${allowlist
  .map((key) => `${key}=${resolvedValues.get(key) ?? ''}`)
  .join('\n')}\n`;

fs.writeFileSync(outputPath, serialized, 'utf8');
console.log(`Wrote packaged runtime env to ${outputPath}`);

const resolvedProfile = resolveBuildProfileFromEnvironment(process.env, { projectRoot });
const capabilityManifest = {
  schema_version: 1,
  profile: resolvedProfile.profile,
  platform: resolvedProfile.platform,
  architecture: resolvedProfile.architecture,
  features: resolvedProfile.features,
};
fs.writeFileSync(
  capabilitiesPath,
  `${JSON.stringify(capabilityManifest, null, 2)}\n`,
  'utf8',
);
console.log(`Wrote build capability manifest to ${capabilitiesPath}`);
