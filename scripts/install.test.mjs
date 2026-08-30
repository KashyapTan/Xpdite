import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';

const installer = path.resolve('scripts/install.sh');
const releases = JSON.stringify([
  {
    draft: false,
    prerelease: false,
    tag_name: 'v1.2.3',
    assets: [
      {
        name: 'Xpdite-1.2.3-mac-arm64.dmg',
        browser_download_url: 'https://example.test/Xpdite-1.2.3-mac-arm64.dmg',
      },
      {
        name: 'Xpdite-1.2.3-mac-x64.dmg',
        browser_download_url: 'https://example.test/Xpdite-1.2.3-mac-x64.dmg',
      },
    ],
  },
]);

for (const [architecture, expectedAsset] of [
  ['arm64', 'Xpdite-1.2.3-mac-arm64.dmg'],
  ['x86_64', 'Xpdite-1.2.3-mac-x64.dmg'],
]) {
  test(`installer selects ${expectedAsset} for ${architecture}`, () => {
    const result = spawnSync('bash', [installer], {
      encoding: 'utf8',
      env: {
        ...process.env,
        XPDITE_OS_OVERRIDE: 'Darwin',
        XPDITE_ARCH_OVERRIDE: architecture,
        XPDITE_DRY_RUN: '1',
        XPDITE_RELEASES_JSON: releases,
      },
    });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, new RegExp(`asset=${expectedAsset.replaceAll('.', '\\.')}`));
  });
}

test('installer reports release availability when the native asset is absent', () => {
  const result = spawnSync('bash', [installer], {
    encoding: 'utf8',
    env: {
      ...process.env,
      XPDITE_OS_OVERRIDE: 'Darwin',
      XPDITE_ARCH_OVERRIDE: 'x86_64',
      XPDITE_DRY_RUN: '1',
      XPDITE_RELEASES_JSON: JSON.stringify([]),
    },
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Could not find a macOS x86_64 Xpdite release asset/);
});
