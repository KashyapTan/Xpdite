/**
 * Adapters module exports
 * 
 * All adapters wrap the Chat SDK adapters for unified messaging platform support.
 */

export { createTelegramAdapter } from './telegram.js';
export type { TelegramAdapter } from './telegram.js';

export { createDiscordAdapter } from './discord.js';
export type { DiscordAdapter } from './discord.js';

export { createWhatsAppAdapter } from './whatsapp.js';
export type { WhatsAppAdapter } from './whatsapp.js';
