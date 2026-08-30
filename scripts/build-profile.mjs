import path from 'node:path';
import { spawnSync } from 'node:child_process';

const PLATFORM_ALIASES = new Map([
  ['darwin', 'darwin'],
  ['mac', 'darwin'],
  ['macos', 'darwin'],
  ['win', 'win32'],
  ['win32', 'win32'],
  ['windows', 'win32'],
  ['linux', 'linux'],
]);

const ARCH_ALIASES = new Map([
  ['arm64', 'arm64'],
  ['aarch64', 'arm64'],
  ['x64', 'x64'],
  ['x86_64', 'x64'],
  ['amd64', 'x64'],
]);

const PROFILE_DEFINITIONS = {
  full: {
    groups: ['dev', 'transcription', 'advanced-audio', 'local-embeddings'],
    features: {
      microphone_dictation: true,
      meeting_transcription: true,
      youtube_whisper_fallback: true,
      whisperx_alignment: true,
      speaker_diarization: true,
      local_sentence_embeddings: true,
    },
  },
  'mac-intel-transcription': {
    groups: ['dev', 'transcription'],
    features: {
      microphone_dictation: true,
      meeting_transcription: true,
      youtube_whisper_fallback: true,
      whisperx_alignment: false,
      speaker_diarization: false,
      local_sentence_embeddings: false,
    },
  },
};

const SUPPORTED_TARGETS = new Map([
  ['darwin:arm64', 'full'],
  ['darwin:x64', 'mac-intel-transcription'],
  ['win32:x64', 'full'],
  ['linux:x64', 'full'],
]);

function normalizeValue(value, aliases, label) {
  const normalized = aliases.get(String(value ?? '').trim().toLowerCase());
  if (!normalized) {
    throw new Error(`Unsupported target ${label}: ${value || '(empty)'}`);
  }
  return normalized;
}

export function normalizeTargetPlatform(platform) {
  return normalizeValue(platform, PLATFORM_ALIASES, 'platform');
}

export function normalizeTargetArchitecture(architecture) {
  return normalizeValue(architecture, ARCH_ALIASES, 'architecture');
}

function environmentPlatformName(platform) {
  if (platform === 'darwin') return 'macos';
  if (platform === 'win32') return 'windows';
  return platform;
}

export function resolveBuildProfile({
  platform = process.platform,
  architecture = process.arch,
  profile,
  projectRoot = process.cwd(),
} = {}) {
  const targetPlatform = normalizeTargetPlatform(platform);
  const targetArch = normalizeTargetArchitecture(architecture);
  const targetKey = `${targetPlatform}:${targetArch}`;
  const canonicalProfile = SUPPORTED_TARGETS.get(targetKey);

  if (!canonicalProfile) {
    throw new Error(
      `Unsupported Xpdite build target ${targetPlatform}/${targetArch}. ` +
      'Supported targets: macOS arm64, macOS x64, Windows x64, and Linux x64.',
    );
  }

  const explicitProfile = String(profile ?? '').trim();
  if (explicitProfile && !PROFILE_DEFINITIONS[explicitProfile]) {
    throw new Error(`Unknown Xpdite build profile: ${explicitProfile}`);
  }
  if (explicitProfile && explicitProfile !== canonicalProfile) {
    throw new Error(
      `Profile ${explicitProfile} is incompatible with ${targetPlatform}/${targetArch}; ` +
      `expected ${canonicalProfile}.`,
    );
  }

  const resolvedProfile = explicitProfile || canonicalProfile;
  const definition = PROFILE_DEFINITIONS[resolvedProfile];
  const environmentName = [
    environmentPlatformName(targetPlatform),
    targetArch,
    resolvedProfile,
  ].join('-');
  const environmentDir = path.resolve(projectRoot, '.venv-build', environmentName);

  return {
    platform: targetPlatform,
    architecture: targetArch,
    profile: resolvedProfile,
    groups: [...definition.groups],
    features: { ...definition.features },
    environmentDir,
  };
}

export function buildProfileEnvironment(resolved, baseEnvironment = process.env) {
  return {
    ...baseEnvironment,
    UV_PROJECT_ENVIRONMENT: resolved.environmentDir,
    XPDITE_TARGET_PLATFORM: resolved.platform,
    XPDITE_TARGET_ARCH: resolved.architecture,
    XPDITE_BUILD_PROFILE: resolved.profile,
    XPDITE_PYTHON_ENV: resolved.environmentDir,
    XPDITE_BUILD_GROUPS: resolved.groups.join(','),
    XPDITE_BUILD_FEATURES: Object.entries(resolved.features)
      .filter(([, enabled]) => enabled)
      .map(([feature]) => feature)
      .join(','),
  };
}

export function pythonSyncArguments(resolved, pythonVersion = '3.13') {
  return [
    'sync',
    '--locked',
    '--no-default-groups',
    '--python',
    pythonVersion,
    ...resolved.groups.flatMap((group) => ['--group', group]),
  ];
}

export function resolveBuildProfileFromEnvironment(environment = process.env, options = {}) {
  return resolveBuildProfile({
    platform: environment.XPDITE_TARGET_PLATFORM || options.platform || process.platform,
    architecture: environment.XPDITE_TARGET_ARCH || options.architecture || process.arch,
    profile: environment.XPDITE_BUILD_PROFILE || options.profile,
    projectRoot: options.projectRoot || process.cwd(),
  });
}

export function assertNativeHost(resolved, {
  hostPlatform = process.platform,
  hostArchitecture = process.arch,
  isRosettaTranslated,
} = {}) {
  const normalizedHostPlatform = normalizeTargetPlatform(hostPlatform);
  const normalizedHostArchitecture = normalizeTargetArchitecture(hostArchitecture);
  const translated = isRosettaTranslated ?? (
    normalizedHostPlatform === 'darwin'
    && normalizedHostArchitecture === 'x64'
    && spawnSync('/usr/sbin/sysctl', ['-in', 'sysctl.proc_translated'], {
      encoding: 'utf8',
      shell: false,
    }).stdout?.trim() === '1'
  );

  if (
    resolved.platform !== normalizedHostPlatform
    || resolved.architecture !== normalizedHostArchitecture
    || translated
  ) {
    const translationLabel = translated ? ' under Rosetta' : '';
    throw new Error(
      `Native build required for ${resolved.platform}/${resolved.architecture}; ` +
      `current host is ${normalizedHostPlatform}/${normalizedHostArchitecture}${translationLabel}. ` +
      'Cross-architecture and Rosetta builds are not supported.',
    );
  }
}

export const BUILD_PROFILES = Object.freeze(PROFILE_DEFINITIONS);
