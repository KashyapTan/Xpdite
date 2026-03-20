/**
 * Utility functions for tool call display logic.
 * Kept separate from component files for Fast Refresh compatibility.
 */
import type { ToolCall } from '../../types';

type ToolArgs = Record<string, unknown>;

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

export function getServerSummaryFragment(server: string, count: number): string {
  if (server === 'filesystem') {
    return `accessed ${pluralize(count, 'file')}`;
  }
  if (server === 'websearch') {
    return count === 1 ? 'searched the web' : `used ${pluralize(count, 'web tool')}`;
  }
  if (server === 'terminal') {
    return `ran ${pluralize(count, 'terminal action')}`;
  }
  if (server === 'sub_agent') {
    return `spawned ${pluralize(count, 'sub-agent')}`;
  }
  if (server === 'demo') {
    return `performed ${pluralize(count, 'calculation')}`;
  }
  if (server === 'gmail') {
    return `used ${pluralize(count, 'gmail action')}`;
  }
  if (server === 'calendar') {
    return `used ${pluralize(count, 'calendar action')}`;
  }
  if (server === 'video_watcher') {
    return count === 1 ? 'watched a YouTube video' : `watched ${pluralize(count, 'YouTube video')}`;
  }
  if (server === 'skills') {
    return count === 1 ? 'checked skills' : `used ${pluralize(count, 'skill action')}`;
  }

  return `used ${server}`;
}

export function getHumanReadableDescription(tc: ToolCall): { badge: string; text: string } {
  const { server, name, args } = tc;

  let badge = server.toUpperCase();
  let text = `${name}(${JSON.stringify(args)})`;

  if (server === 'demo') {
    badge = 'CALCULATOR';
    if (name === 'add') text = `Adding ${args.a} + ${args.b}`;
    if (name === 'divide') text = `Dividing ${args.a} / ${args.b}`;
  } else if (server === 'filesystem') {
    badge = 'FILE';
    if (name === 'list_directory') text = `Listing contents of '${args.path}'`;
    if (name === 'read_file') text = `Reading file '${args.path}'`;
    if (name === 'write_file') text = `Writing to file '${args.path}'`;
    if (name === 'create_folder') text = `Creating folder '${args.folder_name}' in '${args.path}'`;
    if (name === 'move_file') text = `Moving '${args.source_path}' to '${args.destination_folder}'`;
    if (name === 'rename_file') text = `Renaming '${args.source_path}' to '${args.new_name}'`;
    if (name === 'glob_files') {
      text = addLocationSuffix(
        `Finding files matching ${quote(getStringArg(args, 'pattern'), 'this pattern')}`,
        getStringArg(args, 'base_path'),
      );
    }
    if (name === 'grep_files') {
      const pattern = getStringArg(args, 'pattern');
      const isRegex = getBooleanArg(args, 'is_regex');
      const fileGlob = getStringArg(args, 'file_glob');
      const scope = getStringArg(args, 'path');
      text = addLocationSuffix(
        `Searching files for ${isRegex ? `regex ${quote(pattern, 'this pattern')}` : quote(pattern, 'this text')}`,
        scope,
      );
      if (fileGlob && fileGlob !== '**/*') {
        text += ` matching '${fileGlob}'`;
      }
    }
  } else if (server === 'websearch') {
    badge = 'WEB';
    if (name === 'search_web_pages') text = `Searching the web for "${args.query}"`;
    if (name === 'read_website') text = `Reading website "${args.url}"`;
  } else if (server === 'terminal') {
    badge = 'TERMINAL';
    if (name === 'run_command') text = `Running: ${args.command}`;
    if (name === 'find_files') text = `Finding files: ${args.pattern}`;
    if (name === 'get_environment') text = `Getting environment info`;
    if (name === 'request_session_mode') text = `Requesting terminal session`;
    if (name === 'end_session_mode') text = `Ending terminal session`;
    if (name === 'send_input') text = `Sending input to terminal session '${args.session_id}'`;
    if (name === 'read_output') text = `Reading terminal output from '${args.session_id}'`;
    if (name === 'kill_process') text = `Stopping terminal session '${args.session_id}'`;
  } else if (server === 'sub_agent') {
    badge = 'SUB-AGENT';
    const agentName = args.agent_name || 'Sub-Agent';
    const tier = args.model_tier || 'fast';
    // Show live progress description while running, otherwise static label
    text = tc.description || `${agentName} (${tier})`;
  } else if (server === 'gmail') {
    badge = 'GMAIL';
    if (name === 'search_emails') text = `Searching Gmail for ${quote(getStringArg(args, 'query'), 'emails')}`;
    if (name === 'read_email') text = `Reading Gmail message ${quote(getStringArg(args, 'message_id'), 'this email')}`;
    if (name === 'send_email') text = `Sending email to ${quote(getStringArg(args, 'to'), 'recipient')} about ${quote(getStringArg(args, 'subject'), 'a subject')}`;
    if (name === 'reply_to_email') text = `Replying to Gmail message ${quote(getStringArg(args, 'message_id'), 'this email')}`;
    if (name === 'create_draft') text = `Drafting email to ${quote(getStringArg(args, 'to'), 'recipient')} about ${quote(getStringArg(args, 'subject'), 'a subject')}`;
    if (name === 'trash_email') text = `Moving Gmail message ${quote(getStringArg(args, 'message_id'), 'this email')} to trash`;
    if (name === 'list_labels') text = 'Listing Gmail labels';
    if (name === 'modify_labels') {
      text = `Updating Gmail labels on ${quote(getStringArg(args, 'message_id'), 'this email')}`;
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
    }
    if (name === 'get_unread_count') text = 'Checking unread Gmail count';
    if (name === 'get_email_thread') text = `Reading Gmail thread ${quote(getStringArg(args, 'thread_id'), 'this thread')}`;
  } else if (server === 'calendar') {
    badge = 'CALENDAR';
    if (name === 'get_events') {
      const daysAhead = getStringArg(args, 'days_ahead') ?? '7';
      text = `Checking upcoming events for the next ${daysAhead} day(s)`;
    }
    if (name === 'search_events') {
      const daysAhead = getStringArg(args, 'days_ahead') ?? '30';
      text = `Searching calendar for ${quote(getStringArg(args, 'query'), 'events')} in the next ${daysAhead} day(s)`;
    }
    if (name === 'get_event') text = `Reading calendar event ${quote(getStringArg(args, 'event_id'), 'this event')}`;
    if (name === 'create_event') text = `Creating calendar event ${quote(getStringArg(args, 'title'), 'new event')}`;
    if (name === 'update_event') text = `Updating calendar event ${quote(getStringArg(args, 'event_id'), 'this event')}`;
    if (name === 'delete_event') text = `Deleting calendar event ${quote(getStringArg(args, 'event_id'), 'this event')}`;
    if (name === 'quick_add_event') text = `Quick-adding calendar event from ${quote(getStringArg(args, 'text'), 'this description')}`;
    if (name === 'list_calendars') text = 'Listing calendars';
    if (name === 'get_free_busy') {
      text = `Checking calendar availability from ${quote(getStringArg(args, 'time_min'), 'start')} to ${quote(getStringArg(args, 'time_max'), 'end')}`;
    }
  } else if (server === 'video_watcher') {
    badge = 'YOUTUBE';
    if (name === 'watch_youtube_video') {
      text = `Watching YouTube video ${quote(getStringArg(args, 'url'), 'link')}`;
    }
  } else if (server === 'skills') {
    badge = 'SKILLS';
    if (name === 'list_skills') text = 'Listing available skills';
    if (name === 'use_skill') text = `Loading skill '${getStringArg(args, 'skill_name') || 'unknown'}'`;
  }

  return { badge, text };
}


