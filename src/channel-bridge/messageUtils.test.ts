import { describe, expect, test, vi } from 'vitest';

import {
  createWhatsAppOutboundTracker,
  decodeBaileysThreadId,
  getInboundSenderId,
  getMessageText,
  getMessageTimestampMs,
  normalizeWhatsAppSenderId,
} from './messageUtils.js';

describe('normalizeWhatsAppSenderId', () => {
  test('normalizes JID device suffix', () => {
    expect(normalizeWhatsAppSenderId('15551234567:7@s.whatsapp.net')).toBe('15551234567@s.whatsapp.net');
  });

  test('keeps non-device JID unchanged', () => {
    expect(normalizeWhatsAppSenderId('15551234567@s.whatsapp.net')).toBe('15551234567@s.whatsapp.net');
  });
});

describe('decodeBaileysThreadId', () => {
  test('decodes encoded baileys thread id', () => {
    const jid = '15551234567@s.whatsapp.net';
    const encoded = Buffer.from(jid).toString('base64url');

    expect(decodeBaileysThreadId(`baileys:${encoded}`)).toBe(jid);
  });

  test('returns null for non-baileys prefix', () => {
    expect(decodeBaileysThreadId('telegram:12345')).toBeNull();
  });
});

describe('getInboundSenderId', () => {
  test('normalizes whatsapp user id from author', () => {
    expect(
      getInboundSenderId('whatsapp', 'baileys:ignored', {
        userId: '15551234567:12@s.whatsapp.net',
      }),
    ).toBe('15551234567@s.whatsapp.net');
  });

  test('falls back to decoded thread jid when author id unknown', () => {
    const jid = '17323187425@s.whatsapp.net';
    const encoded = Buffer.from(jid).toString('base64url');

    expect(
      getInboundSenderId('whatsapp', `baileys:${encoded}`, {
        userName: 'unknown',
      }),
    ).toBe(jid);
  });

  test('uses decoded thread jid when whatsapp author userName is display name', () => {
    const jid = '15557654321@s.whatsapp.net';
    const encoded = Buffer.from(jid).toString('base64url');

    expect(
      getInboundSenderId('whatsapp', `baileys:${encoded}`, {
        userName: 'Kashyap',
      }),
    ).toBe(jid);
  });

  test('keeps non-whatsapp sender id unchanged', () => {
    expect(
      getInboundSenderId('telegram', 'telegram:123', {
        userId: '111',
      }),
    ).toBe('111');
  });
});

describe('getMessageTimestampMs', () => {
  test('uses metadata dateSent when valid', () => {
    const ts = new Date('2025-01-01T00:00:00.000Z');
    expect(getMessageTimestampMs({ metadata: { dateSent: ts } })).toBe(ts.getTime());
  });

  test('falls back to raw timestamp in seconds', () => {
    expect(getMessageTimestampMs({ raw: { messageTimestamp: 1700000000 } })).toBe(1700000000000);
  });

  test('falls back to raw timestamp object with low/high fields', () => {
    expect(
      getMessageTimestampMs({
        raw: {
          messageTimestamp: {
            low: 1700000000,
            high: 0,
          },
        },
      }),
    ).toBe(1700000000000);
  });

  test('falls back to raw timestamp object with toNumber', () => {
    expect(
      getMessageTimestampMs({
        raw: {
          messageTimestamp: {
            toNumber: () => 1700000000,
          },
        },
      }),
    ).toBe(1700000000000);
  });

  test('returns undefined for epoch fallback values', () => {
    expect(getMessageTimestampMs({ metadata: { dateSent: new Date(0) } })).toBeUndefined();
    expect(getMessageTimestampMs({ createdAt: new Date(0) })).toBeUndefined();
  });
});

describe('getMessageText', () => {
  test('returns message.text when present', () => {
    expect(getMessageText({ text: 'hello' })).toBe('hello');
  });

  test('reads WhatsApp raw conversation text when top-level text is empty', () => {
    expect(
      getMessageText({
        text: '',
        raw: {
          message: {
            conversation: '/pair 123456',
          },
        },
      }),
    ).toBe('/pair 123456');
  });

  test('reads WhatsApp extended text payload', () => {
    expect(
      getMessageText({
        raw: {
          message: {
            extendedTextMessage: {
              text: 'hi from extended',
            },
          },
        },
      }),
    ).toBe('hi from extended');
  });

  test('reads WhatsApp ephemeral wrapped text payload', () => {
    expect(
      getMessageText({
        raw: {
          message: {
            ephemeralMessage: {
              message: {
                conversation: 'ephemeral hello',
              },
            },
          },
        },
      }),
    ).toBe('ephemeral hello');
  });

  test('reads WhatsApp view-once wrapped extended text payload', () => {
    expect(
      getMessageText({
        raw: {
          message: {
            viewOnceMessageV2: {
              message: {
                extendedTextMessage: {
                  text: '/pair 654321',
                },
              },
            },
          },
        },
      }),
    ).toBe('/pair 654321');
  });
});

describe('createWhatsAppOutboundTracker', () => {
  test('tracks outbound message ids and expires by ttl', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00.000Z'));

    const tracker = createWhatsAppOutboundTracker(5000, 5000, 1000);
    tracker.remember('msg-1', 'baileys:thread', 'ack');

    expect(tracker.shouldIgnore('msg-1', 'baileys:thread', 'ack')).toBe(true);

    vi.advanceTimersByTime(6000);

    expect(tracker.shouldIgnore('msg-1', 'baileys:thread', 'ack')).toBe(false);

    vi.useRealTimers();
  });

  test('evicts oldest entries when max size is exceeded', () => {
    const tracker = createWhatsAppOutboundTracker(60_000, 2);

    tracker.remember('msg-1', 'baileys:t', 'one');
    tracker.remember('msg-2', 'baileys:t', 'two');
    tracker.remember('msg-3', 'baileys:t', 'three');

    expect(tracker.shouldIgnore('msg-1', 'baileys:t', 'one')).toBe(false);
    expect(tracker.shouldIgnore('msg-2', 'baileys:t', 'two')).toBe(true);
    expect(tracker.shouldIgnore('msg-3', 'baileys:t', 'three')).toBe(true);
  });

  test('suppresses outbound echoes by thread+content when id differs', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00.000Z'));

    const tracker = createWhatsAppOutboundTracker(120_000, 5000, 15_000);
    tracker.remember(undefined, 'baileys:thread-a', 'Got it, working on it...');

    expect(
      tracker.shouldIgnore('inbound-different-id', 'baileys:thread-a', 'Got it, working on it...'),
    ).toBe(true);

    vi.advanceTimersByTime(16_000);

    expect(
      tracker.shouldIgnore('inbound-different-id', 'baileys:thread-a', 'Got it, working on it...'),
    ).toBe(false);

    vi.useRealTimers();
  });
});
