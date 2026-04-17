import type { Platform } from './types.js';

interface MessageAuthorLike {
  userId?: string;
  platformId?: string;
  userName?: string;
}

interface MessageWithTimestampLike {
  metadata?: {
    dateSent?: Date;
  };
  createdAt?: Date;
  raw?: unknown;
}

interface MessageWithTextLike {
  text?: string;
  raw?: unknown;
}

interface MessageWithIdLike {
  id: string;
}

interface MessageWithWhatsAppKeyLike {
  raw?: unknown;
}

interface WhatsAppMessageKeyLike {
  fromMe?: boolean;
}

type ObjectLike = Record<string, unknown>;

export function normalizeWhatsAppSenderId(senderId: string): string {
  return senderId.replace(/:[0-9]+@/, '@');
}

export function normalizeWhatsAppJid(jid: string): string {
  return normalizeWhatsAppSenderId(jid);
}

function isLikelyWhatsAppJid(value: string): boolean {
  return value.includes('@') && !value.startsWith('unknown@');
}

function normalizeTimestampValue(value: number): number | undefined {
  if (!Number.isFinite(value) || value <= 0) {
    return undefined;
  }

  return value < 1_000_000_000_000 ? value * 1000 : value;
}

function parseNumericTimestampCandidate(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return value;
  }

  if (typeof value === 'bigint' && value > 0n) {
    return Number(value);
  }

  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }

  if (!value || typeof value !== 'object') {
    return undefined;
  }

  const maybeValue = value as {
    toNumber?: () => number;
    valueOf?: () => unknown;
    low?: number;
    high?: number;
    seconds?: unknown;
  };

  if (typeof maybeValue.toNumber === 'function') {
    const parsed = maybeValue.toNumber();
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }

  const secondsCandidate = parseNumericTimestampCandidate(maybeValue.seconds);
  if (secondsCandidate !== undefined) {
    return secondsCandidate;
  }

  if (typeof maybeValue.low === 'number' && typeof maybeValue.high === 'number') {
    const low = maybeValue.low >>> 0;
    const high = maybeValue.high >>> 0;
    const combined = high * 2 ** 32 + low;
    if (Number.isFinite(combined) && combined > 0) {
      return combined;
    }
  }

  if (typeof maybeValue.valueOf === 'function') {
    const valueOfResult = maybeValue.valueOf();
    if (valueOfResult !== value) {
      return parseNumericTimestampCandidate(valueOfResult);
    }
  }

  return undefined;
}

function getRawTimestampMs(raw: unknown): number | undefined {
  if (!raw || typeof raw !== 'object') {
    return undefined;
  }

  const candidate = raw as {
    messageTimestamp?: unknown;
    message_timestamp?: unknown;
    timestamp?: unknown;
  };

  const parsed = parseNumericTimestampCandidate(
    candidate.messageTimestamp ?? candidate.message_timestamp ?? candidate.timestamp,
  );

  if (parsed === undefined) {
    return undefined;
  }

  return normalizeTimestampValue(parsed);
}

export function decodeBaileysThreadId(threadId: string): string | null {
  const prefix = 'baileys:';
  if (!threadId.startsWith(prefix)) {
    return null;
  }

  const encodedJid = threadId.slice(prefix.length);
  if (!encodedJid) {
    return null;
  }

  try {
    return Buffer.from(encodedJid, 'base64url').toString();
  } catch {
    return null;
  }
}

export function encodeBaileysThreadId(jid: string): string {
  return `baileys:${Buffer.from(jid).toString('base64url')}`;
}

export function getInboundSenderId(
  platform: Platform,
  threadId: string,
  author: MessageAuthorLike,
): string {
  const platformId = author.userId ?? author.platformId;

  if (platform !== 'whatsapp') {
    return platformId ?? author.userName ?? 'unknown';
  }

  const decodedJid = decodeBaileysThreadId(threadId);
  const fallbackJid = decodedJid && isLikelyWhatsAppJid(decodedJid) ? decodedJid : undefined;

  let resolvedSenderId = platformId;
  if (!resolvedSenderId || !isLikelyWhatsAppJid(resolvedSenderId)) {
    resolvedSenderId = fallbackJid ?? resolvedSenderId ?? author.userName ?? 'unknown';
  }

  return normalizeWhatsAppSenderId(resolvedSenderId);
}

export function getMessageTimestampMs(message: MessageWithTimestampLike): number | undefined {
  const metadataTimestamp = message.metadata?.dateSent;
  if (metadataTimestamp instanceof Date) {
    const ts = metadataTimestamp.getTime();
    if (!Number.isNaN(ts) && ts > 0) {
      return ts;
    }
  }

  const createdAt = message.createdAt;
  if (createdAt instanceof Date) {
    const ts = createdAt.getTime();
    if (!Number.isNaN(ts) && ts > 0) {
      return ts;
    }
  }

  const rawTimestamp = getRawTimestampMs(message.raw);
  if (rawTimestamp !== undefined) {
    return rawTimestamp;
  }

  return undefined;
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }

  return undefined;
}

function isObjectLike(value: unknown): value is ObjectLike {
  return Boolean(value) && typeof value === 'object';
}

function asObject(value: unknown): ObjectLike | undefined {
  return isObjectLike(value) ? value : undefined;
}

function extractTextFromWhatsAppMessage(
  messageNode: unknown,
  depth: number = 0,
): string | undefined {
  if (!isObjectLike(messageNode) || depth > 8) {
    return undefined;
  }

  const directText = firstString(
    messageNode.conversation,
    asObject(messageNode.extendedTextMessage)?.text,
    asObject(messageNode.imageMessage)?.caption,
    asObject(messageNode.videoMessage)?.caption,
    asObject(messageNode.documentMessage)?.caption,
    asObject(messageNode.editedMessage)?.text,
  );
  if (directText) {
    return directText;
  }

  const nestedWrapperCandidates: unknown[] = [
    asObject(messageNode.ephemeralMessage)?.message,
    asObject(messageNode.viewOnceMessage)?.message,
    asObject(messageNode.viewOnceMessageV2)?.message,
    asObject(messageNode.viewOnceMessageV2Extension)?.message,
    asObject(messageNode.documentWithCaptionMessage)?.message,
    asObject(messageNode.editedMessage)?.message,
  ];

  for (const nested of nestedWrapperCandidates) {
    const nestedText = extractTextFromWhatsAppMessage(nested, depth + 1);
    if (nestedText) {
      return nestedText;
    }
  }

  for (const value of Object.values(messageNode)) {
    const nestedMessage = asObject(value)?.message;
    if (!nestedMessage) {
      continue;
    }

    const nestedText = extractTextFromWhatsAppMessage(nestedMessage, depth + 1);
    if (nestedText) {
      return nestedText;
    }
  }

  return undefined;
}

export function getMessageText(message: MessageWithTextLike): string {
  if (typeof message.text === 'string' && message.text.trim()) {
    return message.text;
  }

  if (!message.raw || typeof message.raw !== 'object') {
    return message.text ?? '';
  }

  const raw = message.raw as {
    message?: unknown;
  };

  const extracted = extractTextFromWhatsAppMessage(raw.message);
  if (extracted) {
    return extracted;
  }

  return message.text ?? '';
}

export function stripLeadingDiscordMentions(text: string): string {
  return text.replace(/^(?:<@!?\d+>\s*[,;:-]?\s*)+/, '').trimStart();
}

export function normalizeInboundText(platform: Platform, text: string): string {
  if (platform !== 'discord') {
    return text;
  }

  return stripLeadingDiscordMentions(text);
}

function getWhatsAppMessageKey(message: MessageWithWhatsAppKeyLike): WhatsAppMessageKeyLike | undefined {
  if (!message.raw || typeof message.raw !== 'object') {
    return undefined;
  }

  const raw = message.raw as {
    key?: unknown;
  };

  const key = asObject(raw.key);
  if (!key) {
    return undefined;
  }

  return {
    fromMe: typeof key.fromMe === 'boolean' ? key.fromMe : undefined,
  };
}

export function isWhatsAppSelfAuthoredMessage(message: MessageWithWhatsAppKeyLike): boolean {
  return Boolean(getWhatsAppMessageKey(message)?.fromMe);
}

export function isWhatsAppSelfChatThread(threadId: string, selfJids: string[] = []): boolean {
  if (selfJids.length === 0) {
    return false;
  }

  const threadJid = decodeBaileysThreadId(threadId);
  if (!threadJid) {
    return false;
  }

  const normalizedThreadJid = normalizeWhatsAppJid(threadJid);
  return selfJids.some((selfJid) => normalizeWhatsAppJid(selfJid) === normalizedThreadJid);
}

export function canonicalizeWhatsAppThreadId(
  threadId: string,
): string {
  const threadJid = decodeBaileysThreadId(threadId);
  if (!threadJid) {
    return threadId;
  }

  return encodeBaileysThreadId(normalizeWhatsAppJid(threadJid));
}

export interface WhatsAppOutboundTracker {
  remember: (messageId: string | undefined, threadId: string, text: string) => void;
  shouldIgnore: (messageId: string, threadId: string, text: string) => boolean;
}

export type WhatsAppInboundGateResult =
  | 'allow'
  | 'ignore_non_self_authored'
  | 'ignore_non_self_chat'
  | 'ignore_historical_self_message'
  | 'ignore_outbound_echo';

export interface WhatsAppInboundGateOptions {
  selfJids?: string[];
  bridgeStartTime: number;
  selfHistoryGraceMs: number;
  outboundTracker: Pick<WhatsAppOutboundTracker, 'shouldIgnore'>;
}

export function getWhatsAppInboundGateResult(
  threadId: string,
  message: MessageWithIdLike & MessageWithTextLike & MessageWithTimestampLike & MessageWithWhatsAppKeyLike,
  options: WhatsAppInboundGateOptions,
): WhatsAppInboundGateResult {
  if (!isWhatsAppSelfAuthoredMessage(message)) {
    return 'ignore_non_self_authored';
  }

  if (!isWhatsAppSelfChatThread(threadId, options.selfJids ?? [])) {
    return 'ignore_non_self_chat';
  }

  const msgTimestamp = getMessageTimestampMs(message);
  if (msgTimestamp && msgTimestamp < options.bridgeStartTime - options.selfHistoryGraceMs) {
    return 'ignore_historical_self_message';
  }

  if (options.outboundTracker.shouldIgnore(message.id, threadId, getMessageText(message))) {
    return 'ignore_outbound_echo';
  }

  return 'allow';
}

export function createWhatsAppOutboundTracker(
  ttlMs: number = 120_000,
  maxEntries: number = 5000,
  contentTtlMs: number = 15_000,
): WhatsAppOutboundTracker {
  const outboundMessageIds = new Map<string, number>();
  const outboundMessageBodies = new Map<string, number>();
  const CLEANUP_INTERVAL_MS = 5_000;
  let nextCleanupAt = 0;

  function normalizeBodyText(text: string): string {
    return text.trim().replace(/\s+/g, ' ').toLowerCase();
  }

  function bodyKey(threadId: string, text: string): string {
    return `${threadId}\u0000${normalizeBodyText(text)}`;
  }

  function cleanupExpired(now: number): void {
    for (const [messageId, seenAt] of outboundMessageIds.entries()) {
      if (now - seenAt > ttlMs) {
        outboundMessageIds.delete(messageId);
      }
    }

    for (const [contentKey, seenAt] of outboundMessageBodies.entries()) {
      if (now - seenAt > contentTtlMs) {
        outboundMessageBodies.delete(contentKey);
      }
    }
  }

  function enforceSizeLimits(): void {
    while (outboundMessageIds.size > maxEntries) {
      const oldest = outboundMessageIds.keys().next().value;
      if (!oldest) {
        break;
      }
      outboundMessageIds.delete(oldest);
    }

    while (outboundMessageBodies.size > maxEntries) {
      const oldest = outboundMessageBodies.keys().next().value;
      if (!oldest) {
        break;
      }
      outboundMessageBodies.delete(oldest);
    }
  }

  function runMaintenance(now: number): void {
    if (now >= nextCleanupAt) {
      nextCleanupAt = now + CLEANUP_INTERVAL_MS;
      cleanupExpired(now);
    }

    enforceSizeLimits();
  }

  return {
    remember(messageId: string | undefined, threadId: string, text: string): void {
      const now = Date.now();
      runMaintenance(now);

      if (messageId) {
        outboundMessageIds.set(messageId, now);
      }

      const normalized = normalizeBodyText(text);
      if (normalized) {
        outboundMessageBodies.set(bodyKey(threadId, text), now);
      }

      enforceSizeLimits();
    },

    shouldIgnore(messageId: string, threadId: string, text: string): boolean {
      const now = Date.now();
      runMaintenance(now);
      if (outboundMessageIds.has(messageId)) {
        return true;
      }

      const normalized = normalizeBodyText(text);
      if (!normalized) {
        return false;
      }

      return outboundMessageBodies.has(bodyKey(threadId, text));
    },
  };
}
