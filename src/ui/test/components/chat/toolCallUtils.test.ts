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

    test('summarizes gmail, calendar, and video watchers', () => {
      expect(getServerSummaryFragment('gmail', 1)).toBe('used 1 gmail action');
      expect(getServerSummaryFragment('calendar', 2)).toBe('used 2 calendar actions');
      expect(getServerSummaryFragment('video_watcher', 1)).toBe('watched a YouTube video');
      expect(getServerSummaryFragment('video_watcher', 2)).toBe('watched 2 YouTube videos');
      expect(getServerSummaryFragment('skills', 1)).toBe('checked skills');
    });

    test('falls back for unknown servers', () => {
      expect(getServerSummaryFragment('custom_server', 4)).toBe('used custom_server');
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

    test('covers filesystem branch fallbacks for glob and grep', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'filesystem',
            name: 'glob_files',
            args: { pattern: '   ', base_path: '.' },
          }),
        ),
      ).toEqual({
        badge: 'FILE',
        text: 'Finding files matching this pattern',
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'filesystem',
            name: 'grep_files',
            args: { pattern: 'err.*', is_regex: true, file_glob: '**/*', path: '.' },
          }),
        ),
      ).toEqual({
        badge: 'FILE',
        text: "Searching files for regex 'err.*'",
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
            name: 'spawn',
            args: { agent_name: 'Researcher', model_tier: 'standard' },
            description: 'Reading docs and comparing options',
          }),
        ),
      ).toEqual({
        badge: 'SUB-AGENT',
        text: 'Reading docs and comparing options',
      });
    });

    test('formats gmail actions and label modifications', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'gmail',
            name: 'send_email',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'GMAIL',
        text: "Sending email to recipient about a subject",
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'gmail',
            name: 'modify_labels',
            args: {
              message_id: 'abc123',
              add_labels: 'IMPORTANT',
              remove_labels: 'UNREAD',
            },
          }),
        ),
      ).toEqual({
        badge: 'GMAIL',
        text: "Updating Gmail labels on 'abc123' to add 'IMPORTANT' and remove 'UNREAD'",
      });
    });

    test('formats calendar actions with default fallback values', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'calendar',
            name: 'get_events',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'CALENDAR',
        text: 'Checking upcoming events for the next 7 day(s)',
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'calendar',
            name: 'search_events',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'CALENDAR',
        text: 'Searching calendar for events in the next 30 day(s)',
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'calendar',
            name: 'get_free_busy',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'CALENDAR',
        text: 'Checking calendar availability from start to end',
      });
    });

    test('formats video watcher and skills actions', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'video_watcher',
            name: 'watch_youtube_video',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'YOUTUBE',
        text: 'Watching YouTube video link',
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'skills',
            name: 'list_skills',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'SKILLS',
        text: 'Listing available skills',
      });

      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'skills',
            name: 'use_skill',
            args: {},
          }),
        ),
      ).toEqual({
        badge: 'SKILLS',
        text: "Loading skill 'unknown'",
      });
    });

    test('keeps server badge but falls back to generic text for unknown server tools', () => {
      expect(
        getHumanReadableDescription(
          toolCall({
            server: 'filesystem',
            name: 'unsupported_fs_tool',
            args: { depth: 2 },
          }),
        ),
      ).toEqual({
        badge: 'FILE',
        text: 'unsupported_fs_tool({"depth":2})',
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
        text: 'do_stuff({"alpha":1,"beta":true})',
      });
    });
  });
});

