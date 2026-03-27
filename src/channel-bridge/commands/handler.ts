/**
 * Command Handler
 * 
 * Intercepts and handles commands (/new, /stop, /model, etc.) before
 * they reach the AI. Commands are processed by calling Python endpoints.
 */

import type { 
  Platform, 
  CommandResponse 
} from '../types.js';

export interface CommandHandlerDeps {
  callPython: <T>(endpoint: string, body: unknown) => Promise<T>;
}

export interface CommandHandler {
  /**
   * Check if the message is a command and handle it.
   * Returns null if not a command, or the response message if handled.
   */
  handle: (platform: Platform, senderId: string, senderName: string | undefined, text: string) => Promise<string | null>;
  
  /**
   * Get the help text for all available commands.
   */
  getHelpText: () => string;
  
  /**
   * Check if the text starts with a command prefix.
   */
  isCommand: (text: string) => boolean;
}

// Command name -> handler name mapping
// NOTE: handler names must match Python's mobile_channel.py handle_command() expected values
const COMMANDS: Record<string, { handler: string; acceptsArgs: boolean; description: string }> = {
  '/new': { handler: 'new', acceptsArgs: false, description: 'Start a new conversation' },
  '/stop': { handler: 'stop', acceptsArgs: false, description: 'Stop the current task' },
  '/status': { handler: 'status', acceptsArgs: false, description: 'Check current status' },
  '/model': { handler: 'model', acceptsArgs: true, description: 'List or switch models' },
  '/default': { handler: 'default', acceptsArgs: true, description: 'Set default model for this device' },
  '/help': { handler: 'help', acceptsArgs: false, description: 'Show available commands' },
  '/pair': { handler: 'pair', acceptsArgs: true, description: 'Pair with your Xpdite code' },
};

// Simple logging helpers
function debugLog(message: string): void {
  if (process.env.XPDITE_MOBILE_DEBUG_LOGS === '1') {
    console.log(message);
  }
}

function errorLog(message: string, ...args: unknown[]): void {
  console.error(message, ...args);
}

export function createCommandHandler(deps: CommandHandlerDeps): CommandHandler {
  const helpText = generateHelpText();

  function generateHelpText(): string {
    const lines = ['*Available Commands*\n'];
    for (const [name, info] of Object.entries(COMMANDS)) {
      if (info.acceptsArgs) {
        lines.push(`${name} [args] - ${info.description}`);
      } else {
        lines.push(`${name} - ${info.description}`);
      }
    }
    return lines.join('\n');
  }

  return {
    isCommand(text: string): boolean {
      const trimmed = text.trim().toLowerCase();
      return Object.keys(COMMANDS).some(cmd => 
        trimmed === cmd || trimmed.startsWith(cmd + ' ')
      );
    },

    async handle(platform: Platform, senderId: string, senderName: string | undefined, text: string): Promise<string | null> {
      const trimmed = text.trim();
      const parts = trimmed.split(/\s+/);
      const commandName = parts[0].toLowerCase();
      const args = parts.slice(1);

      const command = COMMANDS[commandName];
      if (!command) {
        return null; // Not a command
      }

      // Handle /help locally
      if (command.handler === 'help') {
        return helpText;
      }

      // Handle /pair specially - goes to pairing endpoint
      if (command.handler === 'pair') {
        if (args.length === 0) {
          return 'Usage: /pair CODE\n\nEnter the 6-digit code shown in Xpdite settings.';
        }

        const pairingCode = args[0].trim();
        debugLog(`[CommandHandler] Attempting to pair ${platform}:${senderId} with code ${pairingCode.substring(0, 2)}****`);

        try {
          const response = await deps.callPython<CommandResponse & { message: string }>('/internal/mobile/pair/verify', {
            platform,
            sender_id: senderId,
            display_name: senderName ?? `${platform}:${senderId}`,
            code: pairingCode,
          });

          debugLog(`[CommandHandler] Pairing response: success=${response.success ?? 'unknown'}, message=${response.message}`);
          return response.message;
        } catch (err) {
          errorLog('[CommandHandler] Pairing error:', err);
          return 'Pairing failed. Please try again or generate a new code in Xpdite.';
        }
      }

      // All other commands go to the command endpoint
      try {
        // The Python /internal/mobile/command endpoint returns { response: "..." }
        const result = await deps.callPython<{ response: string }>('/internal/mobile/command', {
          platform,
          sender_id: senderId,
          command: command.handler,
          args: args.join(' ') || null,
        });
        
        // The response text is in the 'response' field
        return result.response || 'Command executed.';

      } catch (err) {
        errorLog(`[CommandHandler] Error executing ${commandName}:`, err);
        return `Failed to execute ${commandName}. Is Xpdite running?`;
      }
    },

    getHelpText(): string {
      return helpText;
    },
  };
}
