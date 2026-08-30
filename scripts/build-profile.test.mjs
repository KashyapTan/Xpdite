import assert from 'node:assert/strict';
import path from 'node:path';
import test from 'node:test';
import {
  assertNativeHost,
  buildProfileEnvironment,
  pythonSyncArguments,
  resolveBuildProfile,
} from './build-profile.mjs';

test('resolves every supported platform and architecture profile', () => {
  const cases = [
    ['darwin', 'arm64', 'full'],
    ['mac', 'x86_64', 'mac-intel-transcription'],
    ['win32', 'x64', 'full'],
    ['linux', 'amd64', 'full'],
  ];

  for (const [platform, architecture, profile] of cases) {
    assert.equal(resolveBuildProfile({ platform, architecture }).profile, profile);
  }
});

test('returns exact groups and isolated Intel environment', () => {
  const resolved = resolveBuildProfile({
    platform: 'darwin',
    architecture: 'x64',
    projectRoot: '/tmp/xpdite-profile-test',
  });

  assert.deepEqual(resolved.groups, ['dev', 'transcription']);
  assert.equal(
    resolved.environmentDir,
    path.join(
      path.resolve('/tmp/xpdite-profile-test'),
      '.venv-build',
      'macos-x64-mac-intel-transcription',
    ),
  );
  assert.equal(resolved.features.speaker_diarization, false);
  assert.equal(resolved.features.meeting_transcription, true);
  assert.deepEqual(pythonSyncArguments(resolved), [
    'sync',
    '--locked',
    '--no-default-groups',
    '--python',
    '3.13',
    '--group',
    'dev',
    '--group',
    'transcription',
  ]);
});

test('rejects unsupported targets and incompatible overrides', () => {
  assert.throws(
    () => resolveBuildProfile({ platform: 'darwin', architecture: 'ia32' }),
    /Unsupported target architecture/,
  );
  assert.throws(
    () => resolveBuildProfile({
      platform: 'darwin',
      architecture: 'x64',
      profile: 'full',
    }),
    /incompatible/,
  );
});

test('native host validation rejects cross-architecture builds', () => {
  const resolved = resolveBuildProfile({ platform: 'darwin', architecture: 'x64' });
  assert.throws(
    () => assertNativeHost(resolved, { hostPlatform: 'darwin', hostArchitecture: 'arm64' }),
    /Native build required/,
  );
  assert.doesNotThrow(
    () => assertNativeHost(resolved, {
      hostPlatform: 'darwin',
      hostArchitecture: 'x64',
      isRosettaTranslated: false,
    }),
  );
});

test('native host validation rejects Rosetta translation', () => {
  const resolved = resolveBuildProfile({ platform: 'mac', architecture: 'x64' });
  assert.throws(
    () => assertNativeHost(resolved, {
      hostPlatform: 'darwin',
      hostArchitecture: 'x64',
      isRosettaTranslated: true,
    }),
    /under Rosetta/,
  );
});

test('build environment carries the complete profile contract', () => {
  const resolved = resolveBuildProfile({
    platform: 'darwin',
    architecture: 'arm64',
    projectRoot: '/tmp/xpdite-profile-test',
  });
  const environment = buildProfileEnvironment(resolved, { KEEP_ME: 'yes' });

  assert.equal(environment.KEEP_ME, 'yes');
  assert.equal(environment.XPDITE_TARGET_PLATFORM, 'darwin');
  assert.equal(environment.XPDITE_TARGET_ARCH, 'arm64');
  assert.equal(environment.XPDITE_BUILD_PROFILE, 'full');
  assert.equal(environment.XPDITE_PYTHON_ENV, resolved.environmentDir);
  assert.match(environment.XPDITE_BUILD_GROUPS, /advanced-audio/);
});
