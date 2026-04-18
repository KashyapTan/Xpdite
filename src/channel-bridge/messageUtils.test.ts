import { describe, expect, test, vi } from 'vitest';

import {
  canonicalizeWhatsAppThreadId,
  createWhatsAppOutboundTracker,
  encodeBaileysThreadId,
  decodeBaileysThreadId,
  getInboundSenderId,
  normalizeInboundText,
  getWhatsAppInboundGateResult,
  getMessageText,
  getMessageTimestampMs,
  isWhatsAppSelfAuthoredMessage,
  isWhatsAppSelfChatThread,
  normalizeWhatsAppJid,
  normalizeWhatsAppSenderId,
} from './messageUtils.js';

describe('normalizeWhatsAppSenderId', () => {
  test('normalizes JID device suffix', () => {
    expect(normalizeWhatsAppSenderId('15551234567:7@s.whatsapp.net')).toBe('15551234567@s.whatsapp.net');
  });

  test('keeps non-device JID unchanged', () => {
    expect(normalizeWhatsAppSenderId('15551234567@s.whatsapp.net')).toBe('15551234567@s.whatsapp.net');
  });

  test('normalizes lid device suffixes as well', () => {
    expect(normalizeWhatsAppJid('54494595424418:22@lid')).toBe('54494595424418@lid');
  });
});

describe('decodeBaileysThreadId', () => {
  test('encodes baileys thread id from jid', () => {
    const jid = '15551234567@s.whatsapp.net';

    expect(encodeBaileysThreadId(jid)).toBe(`baileys:${Buffer.from(jid).toString('base64url')}`);
  });

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

describe('normalizeInboundText', () => {
  test('strips a leading Discord mention from server commands', () => {
    expect(normalizeInboundText('discord', '<@1234567890> /pair 123456')).toBe('/pair 123456');
  });

  test('strips nick-style Discord mentions and punctuation', () => {
    expect(normalizeInboundText('discord', '<@!1234567890>: hello there')).toBe('hello there');
  });

  test('leaves non-Discord text unchanged', () => {
    expect(normalizeInboundText('telegram', '<@1234567890> /pair 123456')).toBe('<@1234567890> /pair 123456');
  });
});

describe('isWhatsAppSelfAuthoredMessage', () => {
  test('reads fromMe from raw WhatsApp message key', () => {
    expect(
      isWhatsAppSelfAuthoredMessage({
        raw: {
          key: {
            fromMe: true,
          },
        },
      }),
    ).toBe(true);
  });

  test('returns false when raw key is missing', () => {
    expect(isWhatsAppSelfAuthoredMessage({})).toBe(false);
  });
});

describe('isWhatsAppSelfChatThread', () => {
  test('matches decoded thread jid to normalized bot jid', () => {
    const selfJid = '15551234567@s.whatsapp.net';
    const encoded = Buffer.from(selfJid).toString('base64url');

    expect(
      isWhatsAppSelfChatThread(`baileys:${encoded}`, ['15551234567:42@s.whatsapp.net']),
    ).toBe(true);
  });

  test('matches self chat against lid identity when pn identity differs', () => {
    const selfLid = '54494595424418@lid';
    const encoded = Buffer.from(selfLid).toString('base64url');

    expect(
      isWhatsAppSelfChatThread(`baileys:${encoded}`, [
        '17323187425:22@s.whatsapp.net',
        '54494595424418:22@lid',
      ]),
    ).toBe(true);
  });

  test('returns false for non-self chat thread', () => {
    const otherJid = '15557654321@s.whatsapp.net';
    const encoded = Buffer.from(otherJid).toString('base64url');

    expect(
      isWhatsAppSelfChatThread(`baileys:${encoded}`, ['15551234567@s.whatsapp.net']),
    ).toBe(false);
  });
});

describe('canonicalizeWhatsAppThreadId', () => {
  test('re-encodes thread ids with normalized jid while preserving server', () => {
    const rawSelfThread = `baileys:${Buffer.from('54494595424418:22@lid').toString('base64url')}`;

    expect(canonicalizeWhatsAppThreadId(rawSelfThread)).toBe(
      encodeBaileysThreadId('54494595424418@lid'),
    );
  });

  test('leaves already canonical thread ids unchanged', () => {
    const otherThread = `baileys:${Buffer.from('15557654321@s.whatsapp.net').toString('base64url')}`;
    expect(canonicalizeWhatsAppThreadId(otherThread)).toBe(otherThread);
  });
});

describe('getWhatsAppInboundGateResult', () => {
  const selfPnJid = '17323187425:22@s.whatsapp.net';
  const selfLidJid = '54494595424418:22@lid';
  const selfThreadId = `baileys:${Buffer.from('54494595424418@lid').toString('base64url')}`;

  test('allows self-authored messages in self chat when they are not outbound echoes', () => {
    expect(
      getWhatsAppInboundGateResult(
        selfThreadId,
        {
          id: 'user-self-msg',
          text: 'Summarize my day',
          raw: {
            key: {
              fromMe: true,
            },
            messageTimestamp: 1_700_000_008,
          },
        },
        {
          selfJids: [selfPnJid, selfLidJid],
          bridgeStartTime: 1_700_000_010_000,
          selfHistoryGraceMs: 5000,
          outboundTracker: {
            shouldIgnore: () => false,
          },
        },
      ),
    ).toBe('allow');
  });

  test('rejects messages that were not authored by the paired account', () => {
    expect(
      getWhatsAppInboundGateResult(
        selfThreadId,
        {
          id: 'external-msg',
          text: 'hello',
          raw: {
            key: {
              fromMe: false,
            },
          },
        },
        {
          selfJids: [selfPnJid, selfLidJid],
          bridgeStartTime: Date.now(),
          selfHistoryGraceMs: 5000,
          outboundTracker: {
            shouldIgnore: () => false,
          },
        },
      ),
    ).toBe('ignore_non_self_authored');
  });

  test('rejects self-authored messages that are not in self chat', () => {
    const otherThreadId = `baileys:${Buffer.from('15557654321@s.whatsapp.net').toString('base64url')}`;

    expect(
      getWhatsAppInboundGateResult(
        otherThreadId,
        {
          id: 'sent-to-someone-else',
          text: 'hello there',
          raw: {
            key: {
              fromMe: true,
            },
          },
        },
        {
          selfJids: [selfPnJid, selfLidJid],
          bridgeStartTime: Date.now(),
          selfHistoryGraceMs: 5000,
          outboundTracker: {
            shouldIgnore: () => false,
          },
        },
      ),
    ).toBe('ignore_non_self_chat');
  });

  test('rejects historical self messages replayed on reconnect', () => {
    expect(
      getWhatsAppInboundGateResult(
        selfThreadId,
        {
          id: 'historical-self-msg',
          text: 'old prompt',
          raw: {
            key: {
              fromMe: true,
            },
            messageTimestamp: 1_700_000_000,
          },
        },
        {
          selfJids: [selfPnJid, selfLidJid],
          bridgeStartTime: 1_700_000_010_000,
          selfHistoryGraceMs: 5000,
          outboundTracker: {
            shouldIgnore: () => false,
          },
        },
      ),
    ).toBe('ignore_historical_self_message');
  });

  test('rejects outbound echoes in self chat', () => {
    expect(
      getWhatsAppInboundGateResult(
        selfThreadId,
        {
          id: 'assistant-echo',
          text: 'Working on it...',
          raw: {
            key: {
              fromMe: true,
            },
            messageTimestamp: 1_700_000_008,
          },
        },
        {
          selfJids: [selfPnJid, selfLidJid],
          bridgeStartTime: 1_700_000_010_000,
          selfHistoryGraceMs: 5000,
          outboundTracker: {
            shouldIgnore: (messageId, threadId, text) =>
              messageId === 'assistant-echo'
              && threadId === selfThreadId
              && text === 'Working on it...',
          },
        },
      ),
    ).toBe('ignore_outbound_echo');
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
