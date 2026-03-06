/**
 * Utility functions for tool call display logic.
 * Kept separate from component files for Fast Refresh compatibility.
 */
import type { ToolCall } from '../../types';

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
  }

  return { badge, text };
}


