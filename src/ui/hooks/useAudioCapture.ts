/**
 * useAudioCapture hook.
 *
 * Captures system audio (via electron-audio-loopback) and microphone,
 * mixes them into a single mono 16kHz 16-bit PCM stream, and sends
 * chunks to the Python backend as base64-encoded JSON messages over WebSocket.
 *
 * WGC is disabled at the Electron level (see main.ts) to avoid continuous
 * "ProcessFrame failed" errors on Windows. Chromium falls back to DXGI
 * Output Duplication, which is more reliable. Video tracks are stripped
 * per the electron-audio-loopback README.
 */
import { useRef, useCallback } from 'react';


// Audio constants matching backend expectations
const TARGET_SAMPLE_RATE = 16000;
const CHUNK_INTERVAL_MS = 500; // Send a chunk every 500ms

export function useAudioCapture(
    sendMessage: (msg: Record<string, unknown>) => void,
) {
    const audioContextRef = useRef<AudioContext | null>(null);
    const loopbackStreamRef = useRef<MediaStream | null>(null);
    const micStreamRef = useRef<MediaStream | null>(null);
    const processorRef = useRef<ScriptProcessorNode | null>(null);
    const chunkerIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const pcmBufferRef = useRef<Float32Array[]>([]);

    // Shared cleanup logic — used by both stopCapture and startCapture's
    // error/double-start paths. Operates only on refs so it's safe to call
    // from any callback regardless of hook ordering.
    const cleanupRefs = useCallback(() => {
        if (chunkerIntervalRef.current) {
            clearInterval(chunkerIntervalRef.current);
            chunkerIntervalRef.current = null;
        }
        if (processorRef.current) {
            processorRef.current.disconnect();
            processorRef.current = null;
        }
        if (audioContextRef.current) {
            audioContextRef.current.close();
            audioContextRef.current = null;
        }
        if (loopbackStreamRef.current) {
            loopbackStreamRef.current.getTracks().forEach((t) => t.stop());
            loopbackStreamRef.current = null;
        }
        if (micStreamRef.current) {
            micStreamRef.current.getTracks().forEach((t) => t.stop());
            micStreamRef.current = null;
        }
        pcmBufferRef.current = [];
    }, []);

    const startCapture = useCallback(async () => {
        // Guard against double-start: clean up any existing capture first
        if (loopbackStreamRef.current || audioContextRef.current) {
            cleanupRefs();
        }

        try {
            // 1. Enable loopback audio via electron-audio-loopback
            await window.electronAPI?.enableLoopbackAudio();

            // 2. Get system audio stream via getDisplayMedia.
            //    video: true is required by Chromium — it fails without it.
            const loopbackStream = await navigator.mediaDevices.getDisplayMedia({
                video: true,
                audio: true,
            });

            // Per electron-audio-loopback README: remove video tracks we don't
            // need. With WGC disabled (main.ts), the DXGI capture session tears
            // down cleanly when video tracks are stopped.
            loopbackStream.getVideoTracks().forEach((track) => {
                track.stop();
                loopbackStream.removeTrack(track);
            });
            loopbackStreamRef.current = loopbackStream;

            // Disable loopback override so normal getDisplayMedia works again
            await window.electronAPI?.disableLoopbackAudio();

            // 3. Get microphone stream
            let micStream: MediaStream | null = null;
            try {
                micStream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        channelCount: 1,
                        sampleRate: TARGET_SAMPLE_RATE,
                        echoCancellation: true,
                        noiseSuppression: true,
                    },
                });
                micStreamRef.current = micStream;
            } catch (err) {
                console.warn('Microphone not available, recording system audio only:', err);
            }

            // 4. Create AudioContext and mix streams
            const ctx = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
            audioContextRef.current = ctx;

            const destination = ctx.createMediaStreamDestination();

            // Connect loopback audio
            if (loopbackStream.getAudioTracks().length > 0) {
                const loopbackSource = ctx.createMediaStreamSource(loopbackStream);
                loopbackSource.connect(destination);
            }

            // Connect mic audio
            if (micStream && micStream.getAudioTracks().length > 0) {
                const micSource = ctx.createMediaStreamSource(micStream);
                micSource.connect(destination);
            }

            // 5. Set up ScriptProcessorNode to capture PCM data
            const processor = ctx.createScriptProcessor(4096, 1, 1);
            processorRef.current = processor;

            const mixedSource = ctx.createMediaStreamSource(destination.stream);
            mixedSource.connect(processor);
            // Connect through a zero-gain node so ScriptProcessorNode stays
            // active without echoing captured audio through the speakers.
            const silencer = ctx.createGain();
            silencer.gain.value = 0;
            processor.connect(silencer);
            silencer.connect(ctx.destination);

            processor.onaudioprocess = (e) => {
                const inputData = e.inputBuffer.getChannelData(0);
                pcmBufferRef.current.push(new Float32Array(inputData));
            };

            // 6. Send chunks at regular intervals
            chunkerIntervalRef.current = setInterval(() => {
                const chunks = pcmBufferRef.current;
                if (chunks.length === 0) return;
                pcmBufferRef.current = [];

                // Calculate total samples
                const totalSamples = chunks.reduce((sum, c) => sum + c.length, 0);
                const merged = new Float32Array(totalSamples);
                let offset = 0;
                for (const chunk of chunks) {
                    merged.set(chunk, offset);
                    offset += chunk.length;
                }

                // Convert float32 [-1, 1] to int16 PCM
                const pcm16 = new Int16Array(merged.length);
                for (let i = 0; i < merged.length; i++) {
                    const s = Math.max(-1, Math.min(1, merged[i]));
                    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
                }

                // Convert to base64
                const bytes = new Uint8Array(pcm16.buffer);
                let binary = '';
                for (let i = 0; i < bytes.byteLength; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                const b64 = btoa(binary);

                // Send as JSON message
                sendMessage({
                    type: 'meeting_audio_chunk',
                    audio: b64,
                });
            }, CHUNK_INTERVAL_MS);

        } catch (err) {
            console.error('Failed to start audio capture:', err);
            // Clean up any partially-initialized resources
            cleanupRefs();
            throw err;
        }
    }, [sendMessage, cleanupRefs]);

    const stopCapture = useCallback(() => {
        cleanupRefs();
    }, [cleanupRefs]);

    return { startCapture, stopCapture };
}
