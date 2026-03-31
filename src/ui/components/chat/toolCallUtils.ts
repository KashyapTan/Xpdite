/**
 * Utility functions for tool call display logic.
 * Kept separate from component files for Fast Refresh compatibility.
 * 
 * ## How Tool Display Works
 * 
 * Each tool call has a `server` name and `tool` name. We map these to:
 * - `badge`: A short label shown in the UI (e.g., "FILE", "WEB", "FIGMA")
 * - `text`: A human-readable description of what the tool is doing
 * 
 * ## Adding Display for New Tools
 * 
 * For the best UX, add specific mappings in `TOOL_DISPLAY_CONFIG` below.
 * If no mapping exists, the system falls back to:
 * - Badge: Server name in UPPERCASE (e.g., "figma" -> "FIGMA")
 * - Text: `tool_name(args)` format
 * 
 * To add a new server's display config:
 * 1. Add an entry to `TOOL_DISPLAY_CONFIG` with:
 *    - `badge`: Short label for the badge
 *    - `summaryNoun`: Noun for summary (e.g., "file", "action")
 *    - `summaryVerb`: Optional verb (default: "used")
 *    - `tools`: Optional map of tool_name -> description generator function
 */
import type { ToolCall } from '../../types';

type ToolArgs = Record<string, unknown>;
type ToolTextGenerator = (args: ToolArgs, tc: ToolCall) => string;

// ============================================
// Helper Functions
// ============================================

function getStringArg(args: ToolArgs, key: string): string | undefined {
  const value = args[key];
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || undefined;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return undefined;
}

function getBooleanArg(args: ToolArgs, key: string): boolean {
  return args[key] === true;
}

function truncateText(value: string, maxLength = 60): string {
  return value.length > maxLength ? `${value.slice(0, maxLength - 3)}...` : value;
}

function quote(value: string | undefined, fallback: string): string {
  return value ? `'${truncateText(value)}'` : fallback;
}

function addLocationSuffix(text: string, location: string | undefined, label = 'in'): string {
  return location && location !== '.' ? `${text} ${label} '${location}'` : text;
}

function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * Convert a snake_case or camelCase server name to a display-friendly badge.
 * E.g., "figma" -> "FIGMA", "windows_mcp" -> "WINDOWS", "myServer" -> "MY"
 * Note: Only removes _mcp, _server suffixes (with underscore) and camelCase Server (capitalized)
 */
function formatServerNameAsBadge(server: string): string {
  // Remove common suffixes:
  // - _mcp or _MCP (with underscore)
  // - _server or _SERVER (with underscore)
  // - camelCase Server (must have capital S, preceded by lowercase letter)
  const cleaned = server
    .replace(/_mcp$/i, '')
    .replace(/_server$/i, '')
    .replace(/([a-z])Server$/, '$1');  // Only match capital S (no /i flag)
  
  return cleaned.toUpperCase();
}

/**
 * Convert a tool name to a human-readable format.
 * E.g., "read_file" -> "Read file", "searchEmails" -> "Search emails"
 */
function formatToolName(name: string): string {
  // Handle snake_case
  const spacedName = name.replace(/_/g, ' ');
  // Handle camelCase
  const split = spacedName.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
  // Capitalize first letter
  return split.charAt(0).toUpperCase() + split.slice(1);
}

// ============================================
// Tool Display Configuration
// ============================================

interface ToolDisplayConfig {
  badge: string;
  summaryNoun: string;
  summaryVerb?: string;
  tools?: Record<string, ToolTextGenerator>;
}

/**
 * Display configuration for known servers.
 * 
 * For servers not in this map, we use a dynamic fallback based on
 * the server name.
 */
const TOOL_DISPLAY_CONFIG: Record<string, ToolDisplayConfig> = {
  demo: {
    badge: 'CALCULATOR',
    summaryNoun: 'calculation',
    summaryVerb: 'performed',
    tools: {
      add: (args) => `Adding ${args.a} + ${args.b}`,
      divide: (args) => `Dividing ${args.a} / ${args.b}`,
    },
  },

  filesystem: {
    badge: 'FILE',
    summaryNoun: 'file',
    summaryVerb: 'accessed',
    tools: {
      list_directory: (args) => `Listing contents of '${args.path}'`,
      read_file: (args) => `Reading file '${args.path}'`,
      write_file: (args) => `Writing to file '${args.path}'`,
      create_folder: (args) => `Creating folder '${args.folder_name}' in '${args.path}'`,
      move_file: (args) => `Moving '${args.source_path}' to '${args.destination_folder}'`,
      rename_file: (args) => `Renaming '${args.source_path}' to '${args.new_name}'`,
      glob_files: (args) => addLocationSuffix(
        `Finding files matching ${quote(getStringArg(args, 'pattern'), 'this pattern')}`,
        getStringArg(args, 'base_path'),
      ),
      grep_files: (args) => {
        const pattern = getStringArg(args, 'pattern');
        const isRegex = getBooleanArg(args, 'is_regex');
        const fileGlob = getStringArg(args, 'file_glob');
        const scope = getStringArg(args, 'path');
        let text = addLocationSuffix(
          `Searching files for ${isRegex ? `regex ${quote(pattern, 'this pattern')}` : quote(pattern, 'this text')}`,
          scope,
        );
        if (fileGlob && fileGlob !== '**/*') {
          text += ` matching '${fileGlob}'`;
        }
        return text;
      },
    },
  },

  websearch: {
    badge: 'WEB',
    summaryNoun: 'web tool',
    summaryVerb: 'used',
    tools: {
      search_web_pages: (args) => `Searching the web for "${args.query}"`,
      read_website: (args) => `Reading website "${args.url}"`,
    },
  },

  terminal: {
    badge: 'TERMINAL',
    summaryNoun: 'terminal action',
    summaryVerb: 'ran',
    tools: {
      run_command: (args) => `Running: ${args.command}`,
      find_files: (args) => `Finding files: ${args.pattern}`,
      get_environment: () => 'Getting environment info',
      request_session_mode: () => 'Requesting terminal session',
      end_session_mode: () => 'Ending terminal session',
      send_input: (args) => `Sending input to terminal session '${args.session_id}'`,
      read_output: (args) => `Reading terminal output from '${args.session_id}'`,
      kill_process: (args) => `Stopping terminal session '${args.session_id}'`,
    },
  },

  sub_agent: {
    badge: 'SUB-AGENT',
    summaryNoun: 'sub-agent',
    summaryVerb: 'spawned',
    tools: {
      spawn_agent: (args, tc) => {
        const agentName = args.agent_name || 'Sub-Agent';
        const tier = args.model_tier || 'fast';
        // Show live progress description while running, otherwise static label
        return tc.description || `${agentName} (${tier})`;
      },
    },
  },

  gmail: {
    badge: 'GMAIL',
    summaryNoun: 'gmail action',
    tools: {
      search_emails: (args) => `Searching Gmail for ${quote(getStringArg(args, 'query'), 'emails')}`,
      read_email: (args) => `Reading Gmail message ${quote(getStringArg(args, 'message_id'), 'this email')}`,
      send_email: (args) => `Sending email to ${quote(getStringArg(args, 'to'), 'recipient')} about ${quote(getStringArg(args, 'subject'), 'a subject')}`,
      reply_to_email: (args) => `Replying to Gmail message ${quote(getStringArg(args, 'message_id'), 'this email')}`,
      create_draft: (args) => `Drafting email to ${quote(getStringArg(args, 'to'), 'recipient')} about ${quote(getStringArg(args, 'subject'), 'a subject')}`,
      trash_email: (args) => `Moving Gmail message ${quote(getStringArg(args, 'message_id'), 'this email')} to trash`,
      list_labels: () => 'Listing Gmail labels',
      modify_labels: (args) => {
        let text = `Updating Gmail labels on ${quote(getStringArg(args, 'message_id'), 'this email')}`;
        const addLabels = getStringArg(args, 'add_labels');
        const removeLabels = getStringArg(args, 'remove_labels');
        if (addLabels || removeLabels) {
          const changes = [
            addLabels ? `add ${quote(addLabels, 'labels')}` : '',
            removeLabels ? `remove ${quote(removeLabels, 'labels')}` : '',
          ].filter(Boolean).join(' and ');
          if (changes) {
            text += ` to ${changes}`;
          }
        }
        return text;
      },
      get_unread_count: () => 'Checking unread Gmail count',
      get_email_thread: (args) => `Reading Gmail thread ${quote(getStringArg(args, 'thread_id'), 'this thread')}`,
    },
  },

  calendar: {
    badge: 'CALENDAR',
    summaryNoun: 'calendar action',
    tools: {
      get_events: (args) => {
        const daysAhead = getStringArg(args, 'days_ahead') ?? '7';
        return `Checking upcoming events for the next ${daysAhead} day(s)`;
      },
      search_events: (args) => {
        const daysAhead = getStringArg(args, 'days_ahead') ?? '30';
        return `Searching calendar for ${quote(getStringArg(args, 'query'), 'events')} in the next ${daysAhead} day(s)`;
      },
      get_event: (args) => `Reading calendar event ${quote(getStringArg(args, 'event_id'), 'this event')}`,
      create_event: (args) => `Creating calendar event ${quote(getStringArg(args, 'title'), 'new event')}`,
      update_event: (args) => `Updating calendar event ${quote(getStringArg(args, 'event_id'), 'this event')}`,
      delete_event: (args) => `Deleting calendar event ${quote(getStringArg(args, 'event_id'), 'this event')}`,
      quick_add_event: (args) => `Quick-adding calendar event from ${quote(getStringArg(args, 'text'), 'this description')}`,
      list_calendars: () => 'Listing calendars',
      get_free_busy: (args) => `Checking calendar availability from ${quote(getStringArg(args, 'time_min'), 'start')} to ${quote(getStringArg(args, 'time_max'), 'end')}`,
    },
  },

  video_watcher: {
    badge: 'YOUTUBE',
    summaryNoun: 'YouTube video',
    summaryVerb: 'watched',
    tools: {
      watch_youtube_video: (args) => `Watching YouTube video ${quote(getStringArg(args, 'url'), 'link')}`,
    },
  },

  skills: {
    badge: 'SKILLS',
    summaryNoun: 'skill action',
    tools: {
      list_skills: () => 'Listing available skills',
      use_skill: (args) => `Loading skill '${getStringArg(args, 'skill_name') || 'unknown'}'`,
    },
  },

  memory: {
    badge: 'MEMORY',
    summaryNoun: 'memory action',
    tools: {
      memlist: (args) => {
        const folder = getStringArg(args, 'folder');
        return folder ? `Browsing memory in '${folder}'` : 'Browsing memory';
      },
      memread: (args) => `Reading memory ${quote(getStringArg(args, 'path'), 'file')}`,
      memcommit: (args) => `Saving memory ${quote(getStringArg(args, 'path'), 'file')}`,
    },
  },

  // Windows MCP tools
  windows_mcp: {
    badge: 'WINDOWS',
    summaryNoun: 'windows action',
    tools: {
      list_windows: () => 'Listing open windows',
      focus_window: (args) => `Focusing window: ${getStringArg(args, 'title') || getStringArg(args, 'process_name') || 'window'}`,
      minimize_window: (args) => `Minimizing window: ${getStringArg(args, 'title') || 'window'}`,
      maximize_window: (args) => `Maximizing window: ${getStringArg(args, 'title') || 'window'}`,
      close_window: (args) => `Closing window: ${getStringArg(args, 'title') || 'window'}`,
      get_window_info: (args) => `Getting info for window: ${getStringArg(args, 'title') || 'window'}`,
      take_screenshot: () => 'Taking screenshot',
    },
  },

  // Figma MCP tools (dynamically discovered, but we can add nice descriptions)
  figma: {
    badge: 'FIGMA',
    summaryNoun: 'figma action',
    tools: {
      get_file: (args) => `Getting Figma file ${quote(getStringArg(args, 'file_key'), 'this file')}`,
      get_file_nodes: (args) => `Getting nodes from Figma file ${quote(getStringArg(args, 'file_key'), 'this file')}`,
      get_images: (args) => `Exporting images from Figma file ${quote(getStringArg(args, 'file_key'), 'this file')}`,
      get_comments: (args) => `Getting comments from Figma file ${quote(getStringArg(args, 'file_key'), 'this file')}`,
      post_comment: (args) => `Posting comment to Figma file ${quote(getStringArg(args, 'file_key'), 'this file')}`,
      get_team_projects: (args) => `Getting projects for team ${quote(getStringArg(args, 'team_id'), 'this team')}`,
      get_project_files: (args) => `Getting files from project ${quote(getStringArg(args, 'project_id'), 'this project')}`,
      get_team_components: (args) => `Getting components for team ${quote(getStringArg(args, 'team_id'), 'this team')}`,
      get_component: (args) => `Getting component ${quote(getStringArg(args, 'key'), 'this component')}`,
      get_team_styles: (args) => `Getting styles for team ${quote(getStringArg(args, 'team_id'), 'this team')}`,
      get_style: (args) => `Getting style ${quote(getStringArg(args, 'key'), 'this style')}`,
      whoami: () => 'Getting Figma user info',
      generate_figma_design: (args) => `Generating Figma design: ${quote(getStringArg(args, 'prompt'), 'design')}`,
      add_code_connect_map: () => 'Adding code connect map',
    },
  },
};

// ============================================
// Public API
// ============================================

/**
 * Get a summary fragment for a server's tool calls.
 * Used in the collapsed summary view.
 */
export function getServerSummaryFragment(server: string, count: number): string {
  const config = TOOL_DISPLAY_CONFIG[server];

  if (config) {
    const verb = config.summaryVerb || 'used';
    const noun = config.summaryNoun;

    // Special cases for better grammar
    if (server === 'websearch' && count === 1) {
      return 'searched the web';
    }
    if (server === 'video_watcher' && count === 1) {
      return 'watched a YouTube video';
    }
    if (server === 'skills' && count === 1) {
      return 'checked skills';
    }
    if (server === 'memory' && count === 1) {
      return 'checked memory';
    }

    return `${verb} ${pluralize(count, noun)}`;
  }

  // Fallback for unknown servers
  return `used ${formatServerNameAsBadge(server).toLowerCase()}`;
}

/**
 * Get human-readable badge and text for a tool call.
 */
export function getHumanReadableDescription(tc: ToolCall): { badge: string; text: string } {
  const { server, name, args } = tc;

  const config = TOOL_DISPLAY_CONFIG[server];

  // Use configured display if available
  if (config) {
    const badge = config.badge;
    const toolGenerator = config.tools?.[name];

    if (toolGenerator) {
      return { badge, text: toolGenerator(args as ToolArgs, tc) };
    }

    // Tool exists in config but no specific text generator
    // Use a formatted version of the tool name
    return {
      badge,
      text: `${formatToolName(name)}: ${truncateText(JSON.stringify(args), 80)}`,
    };
  }

  // Fallback for completely unknown servers
  // This ensures any new MCP server will display something reasonable
  return {
    badge: formatServerNameAsBadge(server),
    text: `${formatToolName(name)}: ${truncateText(JSON.stringify(args), 80)}`,
  };
}
