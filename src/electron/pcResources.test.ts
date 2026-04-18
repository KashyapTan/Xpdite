// @vitest-environment node

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { tmpdir } from 'node:os';

import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { bundlePythonResources } from './pcResources.js';

describe('bundlePythonResources', () => {
  const originalCwd = process.cwd();
  let workspaceDir: string;

  beforeEach(() => {
    workspaceDir = fs.mkdtempSync(path.join(tmpdir(), 'xpdite-pc-resources-'));
    process.chdir(workspaceDir);
  });

  afterEach(() => {
    process.chdir(originalCwd);
    fs.rmSync(workspaceDir, { recursive: true, force: true });
  });

  test('copies source files, the Python executable, DLLs, and library files into dist-electron resources', () => {
    fs.mkdirSync(path.join(workspaceDir, 'source', 'services'), { recursive: true });
    fs.writeFileSync(path.join(workspaceDir, 'source', 'services', 'app.py'), 'print("hello")', 'utf8');

    fs.mkdirSync(path.join(workspaceDir, '.venv', 'Scripts'), { recursive: true });
    fs.writeFileSync(path.join(workspaceDir, '.venv', 'Scripts', 'python.exe'), 'python-binary', 'utf8');
    fs.writeFileSync(path.join(workspaceDir, '.venv', 'Scripts', 'python311.dll'), 'dll-binary', 'utf8');

    fs.mkdirSync(path.join(workspaceDir, '.venv', 'Lib', 'site-packages', 'demo'), { recursive: true });
    fs.writeFileSync(
      path.join(workspaceDir, '.venv', 'Lib', 'site-packages', 'demo', '__init__.py'),
      'VALUE = 1',
      'utf8',
    );

    bundlePythonResources();

    const bundledPythonDir = path.join(workspaceDir, 'dist-electron', 'resources', 'python');
    expect(fs.readFileSync(path.join(bundledPythonDir, 'source', 'services', 'app.py'), 'utf8')).toBe('print("hello")');
    expect(fs.readFileSync(path.join(bundledPythonDir, 'python.exe'), 'utf8')).toBe('python-binary');
    expect(fs.readFileSync(path.join(bundledPythonDir, 'python311.dll'), 'utf8')).toBe('dll-binary');
    expect(
      fs.readFileSync(
        path.join(bundledPythonDir, 'Lib', 'site-packages', 'demo', '__init__.py'),
        'utf8',
      ),
    ).toBe('VALUE = 1');
  });

  test('still creates the resource directories when source and virtualenv assets are absent', () => {
    bundlePythonResources();

    expect(fs.existsSync(path.join(workspaceDir, 'dist-electron', 'resources'))).toBe(true);
    expect(fs.existsSync(path.join(workspaceDir, 'dist-electron', 'resources', 'python'))).toBe(true);
  });
});
