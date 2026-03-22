import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useAudioCapture } from '../../hooks/useAudioCapture';

type MockTrack = MediaStreamTrack & {
  stop: ReturnType<typeof vi.fn>;
};

type MockSourceNode = MediaStreamAudioSourceNode & {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
};

type MockAnalyser = AnalyserNode & {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  getByteFrequencyData: ReturnType<typeof vi.fn>;
};

type MockProcessor = ScriptProcessorNode & {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  onaudioprocess: ScriptProcessorNode['onaudioprocess'];
};

type MockGainNode = GainNode & {
  connect: ReturnType<typeof vi.fn>;
};

type MockAudioContext = AudioContext & {
  close: ReturnType<typeof vi.fn>;
  createMediaStreamDestination: ReturnType<typeof vi.fn>;
  createMediaStreamSource: ReturnType<typeof vi.fn>;
  createAnalyser: ReturnType<typeof vi.fn>;
  createScriptProcessor: ReturnType<typeof vi.fn>;
  createGain: ReturnType<typeof vi.fn>;
};

type StreamBundle = {
  stream: MediaStream;
  audioTracks: MockTrack[];
  videoTracks: MockTrack[];
};

type AudioContextHarness = {
  contexts: MockAudioContext[];
  analyserNodes: MockAnalyser[];
  processorNodes: MockProcessor[];
  gainNodes: MockGainNode[];
};

function createMockTrack(kind: 'audio' | 'video'): MockTrack {
  return {
    kind,
    stop: vi.fn(),
  } as unknown as MockTrack;
}

function createMockStream({ audio = 1, video = 0 }: { audio?: number; video?: number } = {}): StreamBundle {
  const audioTracks = Array.from({ length: audio }, () => createMockTrack('audio'));
  const videoTracks = Array.from({ length: video }, () => createMockTrack('video'));

  const stream = {
    getTracks: () => [...audioTracks, ...videoTracks],
    getAudioTracks: () => [...audioTracks],
    getVideoTracks: () => [...videoTracks],
    removeTrack: (track: MediaStreamTrack) => {
      const index = videoTracks.indexOf(track as MockTrack);
      if (index >= 0) {
        videoTracks.splice(index, 1);
      }
    },
  } as unknown as MediaStream;

  return { stream, audioTracks, videoTracks };
}

function createAudioContextHarness(): AudioContextHarness {
  const harness: AudioContextHarness = {
    contexts: [],
    analyserNodes: [],
    processorNodes: [],
    gainNodes: [],
  };

  const AudioContextMock = vi.fn(function mockAudioContext(this: unknown, options?: AudioContextOptions) {
    const mixedStream = createMockStream({ audio: 1 }).stream;

    const analyser = {
      fftSize: 0,
      smoothingTimeConstant: 0,
      frequencyBinCount: 128,
      connect: vi.fn(),
      disconnect: vi.fn(),
      getByteFrequencyData: vi.fn((buffer: Uint8Array) => {
        for (let i = 0; i < buffer.length; i += 1) {
          buffer[i] = (i * 11) % 255;
        }
      }),
    } as unknown as MockAnalyser;

    const processor = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      onaudioprocess: null,
    } as unknown as MockProcessor;

    const gain = {
      gain: { value: 1 },
      connect: vi.fn(),
    } as unknown as MockGainNode;

    const context = {
      sampleRate: options?.sampleRate ?? 44100,
      destination: {} as AudioDestinationNode,
      close: vi.fn().mockResolvedValue(undefined),
      createMediaStreamDestination: vi.fn(() => ({ stream: mixedStream })),
      createMediaStreamSource: vi.fn(() => ({ connect: vi.fn(), disconnect: vi.fn() } as MockSourceNode)),
      createAnalyser: vi.fn(() => analyser),
      createScriptProcessor: vi.fn(() => processor),
      createGain: vi.fn(() => gain),
    } as unknown as MockAudioContext;

    harness.contexts.push(context);
    harness.analyserNodes.push(analyser);
    harness.processorNodes.push(processor);
    harness.gainNodes.push(gain);
    return context;
  });

  Object.defineProperty(globalThis, 'AudioContext', {
    configurable: true,
    writable: true,
    value: AudioContextMock,
  });

  return harness;
}

function floatChunkToBase64(samples: number[]): string {
  const pcm16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    pcm16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }

  const bytes = new Uint8Array(pcm16.buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

describe('useAudioCapture', () => {
  const originalAudioContext = globalThis.AudioContext;
  const originalMediaDevices = navigator.mediaDevices;

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();

    Object.defineProperty(globalThis, 'AudioContext', {
      configurable: true,
      writable: true,
      value: originalAudioContext,
    });

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: originalMediaDevices,
    });
  });

  test('handles happy path start/stop and sends mixed audio chunks', async () => {
    const harness = createAudioContextHarness();
    const loopback = createMockStream({ audio: 1, video: 1 });
    const loopbackVideoTrack = loopback.videoTracks[0];
    const mic = createMockStream({ audio: 1 });

    const getDisplayMedia = vi.fn().mockResolvedValue(loopback.stream);
    const getUserMedia = vi.fn().mockResolvedValue(mic.stream);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia, getUserMedia },
    });

    const sendMessage = vi.fn();
    const onVisualizerFrame = vi.fn();

    const { result } = renderHook(() => useAudioCapture(sendMessage, onVisualizerFrame));

    await act(async () => {
      await result.current.startCapture();
    });

    expect(getDisplayMedia).toHaveBeenCalledWith({ video: true, audio: true });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(loopbackVideoTrack.stop).toHaveBeenCalledTimes(1);

    const processor = harness.processorNodes[0];
    expect(processor).toBeDefined();

    const sample = [0, -1, 1, 0.5];
    processor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => Float32Array.from(sample),
      },
    } as unknown as AudioProcessingEvent);

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith({
      type: 'meeting_audio_chunk',
      audio: floatChunkToBase64(sample),
    });

    await act(async () => {
      vi.advanceTimersByTime(60);
    });

    expect(onVisualizerFrame).toHaveBeenCalledWith(expect.arrayContaining([expect.any(Number)]));

    act(() => {
      result.current.stopCapture();
    });

    expect(harness.contexts[0].close).toHaveBeenCalledTimes(1);
    expect(loopback.audioTracks[0].stop).toHaveBeenCalledTimes(1);
    expect(mic.audioTracks[0].stop).toHaveBeenCalledTimes(1);
    expect(onVisualizerFrame).toHaveBeenLastCalledWith([]);

    const sendCountAfterStop = sendMessage.mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(sendMessage).toHaveBeenCalledTimes(sendCountAfterStop);
  });

  test('falls back to system audio when microphone is unavailable', async () => {
    createAudioContextHarness();
    const loopback = createMockStream({ audio: 1, video: 1 });

    const getDisplayMedia = vi.fn().mockResolvedValue(loopback.stream);
    const micError = new Error('No microphone');
    const getUserMedia = vi.fn().mockRejectedValue(micError);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia, getUserMedia },
    });

    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { result } = renderHook(() => useAudioCapture(vi.fn()));

    await act(async () => {
      await expect(result.current.startCapture()).resolves.toBeUndefined();
    });

    expect(getDisplayMedia).toHaveBeenCalledTimes(1);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      'Microphone not available, recording system audio only:',
      micError,
    );

    act(() => {
      result.current.stopCapture();
    });
  });

  test('throws when neither loopback nor microphone provide audio', async () => {
    createAudioContextHarness();
    const loopback = createMockStream({ audio: 0, video: 1 });
    const loopbackVideoTrack = loopback.videoTracks[0];

    const getDisplayMedia = vi.fn().mockResolvedValue(loopback.stream);
    const getUserMedia = vi.fn().mockRejectedValue(new Error('Mic denied'));
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia, getUserMedia },
    });

    const onVisualizerFrame = vi.fn();
    const { result } = renderHook(() => useAudioCapture(vi.fn(), onVisualizerFrame));

    await act(async () => {
      await expect(result.current.startCapture()).rejects.toThrow(
        'No audio sources available — neither system audio nor microphone could be captured',
      );
    });

    expect(loopbackVideoTrack.stop).toHaveBeenCalledTimes(1);
    expect(onVisualizerFrame).toHaveBeenLastCalledWith([]);
  });

  test('cleans up timers and resets visualizer callback on stop', async () => {
    const harness = createAudioContextHarness();
    const loopback = createMockStream({ audio: 1, video: 1 });
    const mic = createMockStream({ audio: 1 });

    const getDisplayMedia = vi.fn().mockResolvedValue(loopback.stream);
    const getUserMedia = vi.fn().mockResolvedValue(mic.stream);
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia, getUserMedia },
    });

    const onVisualizerFrame = vi.fn();
    const { result } = renderHook(() => useAudioCapture(vi.fn(), onVisualizerFrame));

    await act(async () => {
      await result.current.startCapture();
    });

    await act(async () => {
      vi.advanceTimersByTime(60);
    });
    const visualizerCallsBeforeStop = onVisualizerFrame.mock.calls.length;
    expect(visualizerCallsBeforeStop).toBeGreaterThan(0);

    act(() => {
      result.current.stopCapture();
    });

    expect(harness.analyserNodes[0].disconnect).toHaveBeenCalledTimes(1);
    expect(harness.processorNodes[0].disconnect).toHaveBeenCalledTimes(1);
    expect(onVisualizerFrame).toHaveBeenLastCalledWith([]);

    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(onVisualizerFrame.mock.calls.length).toBe(visualizerCallsBeforeStop + 1);
  });
});
