import { describe, expect, test } from 'vitest';

import type { ToolCall } from '../../../types';
import {
  getHumanReadableDescription,
  getServerSummaryFragment,
} from '../../../components/chat/toolCallUtils';

function toolCall(overrides: Partial<ToolCall>): ToolCall {
  return {
    name: 'unknown_tool',
    args: {},
    server: 'unknown',
    status: 'complete',
    ...overrides,
  };
}

describe('toolCallUtils', () => {
  describe('getServerSummaryFragment', () => {
    test('summarizes known servers', () => {
      expect(getServerSummaryFragment('filesystem', 1)).toBe('accessed 1 file');
      expect(getServerSummaryFragment('filesystem', 2)).toBe('accessed 2 files');
      expect(getServerSummaryFragment('websearch', 1)).toBe('searched the web');
      expect(getServerSummaryFragment('terminal', 2)).toBe('ran 2 terminal actions');
      expect(getServerSummaryFragment('skills', 3)).toBe('used 3 skill actions');
    });

    test('falls back for unknown servers', () => {
      // Note: server names ending with _server are cleaned (suffix removed) for display
      expect(getServerSummaryFragment('custom_mcp', 4)).toBe('used custom');
      // Servers without the suffix show the full name
      expect(getServerSummaryFragment('myserver', 4)).toBe('used myserver');
    });
  });

  describe('getHumanReadableDescription', () => {
    test('formats filesystem actions', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'filesystem',
            name: 'read_file',
            args: { path: 'C:\\tmp\\file.txt' },
          }),
        ),
      ).toEqual({
        badge: 'FILE',
        text: "Reading file 'C:\\tmp\\file.txt'",
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'filesystem',
            name: 'grep_files',
            args: { pattern: 'boot', path: 'src', file_glob: '*.ts', is_regex: false },
          }),
        ),
      ).toEqual({
        badge: 'FILE',
        text: "Searching files for 'boot' in 'src' matching '*.ts'",
      });
    });

    test('formats terminal actions', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'terminal',
            name: 'run_command',
            args: { command: 'bun lint' },
          }),
        ),
      ).toEqual({
        badge: 'TERMINAL',
        text: 'Running: bun lint',
      });
    });

    test('formats websearch actions', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'websearch',
            name: 'search_web_pages',
            args: { query: 'vitest jsdom' },
          }),
        ),
      ).toEqual({
        badge: 'WEB',
        text: 'Searching the web for "vitest jsdom"',
      });
    });

    test('uses live sub-agent description when present', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'sub_agent',
            name: 'spawn_agent',
            args: { agent_name: 'Researcher', model_tier: 'standard' },
            description: 'Reading docs and comparing options',
          }),
        ),
      ).toEqual({
        badge: 'SUB-AGENT',
        text: 'Reading docs and comparing options',
      });
    });

    test('falls back to generic description for unknown tools', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'mystery',
            name: 'do_stuff',
            args: { alpha: 1, beta: true },
          }),
        ),
      ).toEqual({
        badge: 'MYSTERY',
        text: 'Do stuff: {"alpha":1,"beta":true}',
      });
    });
  });
});

