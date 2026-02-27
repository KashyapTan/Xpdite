import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../../contexts/WebSocketContext';
import '../../CSS/MeetingRecorderSettings.css';

interface ComputeInfo {
    backend: string;
    device_name: string;
    vram_gb: number;
    compute_type: string;
}

interface MeetingSettings {
    whisper_model: string;
    keep_audio: string;
    diarization_enabled: string;
}

const MeetingRecorderSettings: React.FC = () => {
    const { send, subscribe } = useWebSocket();
    const [computeInfo, setComputeInfo] = useState<ComputeInfo | null>(null);
    const [settings, setSettings] = useState<MeetingSettings>({
        whisper_model: 'base',
        keep_audio: 'false',
        diarization_enabled: 'true',
    });
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        // Subscribe for WS responses
        const unsubscribe = subscribe((data) => {
            if (data.type === 'meeting_compute_info') {
                setComputeInfo(data.content as ComputeInfo);
            } else if (data.type === 'meeting_settings') {
                setSettings(data.content as MeetingSettings);
                setSaving(false);
            }
        });

        // Request current settings and compute info
        send({ type: 'meeting_get_compute_info' });
        send({ type: 'meeting_get_settings' });

        return unsubscribe;
    }, [send, subscribe]);

    const updateSetting = (key: string, value: string) => {
        setSaving(true);
        send({
            type: 'meeting_update_settings',
            settings: { [key]: value },
        });
        // Optimistic update
        setSettings((prev) => ({ ...prev, [key]: value }));
    };

    const gpuLabel = computeInfo
        ? computeInfo.backend === 'cuda'
            ? `NVIDIA CUDA — ${computeInfo.device_name} (${computeInfo.vram_gb} GB)`
            : 'None (CPU only)'
        : 'Detecting...';

    return (
        <div className="meeting-settings">
            <h2 className="meeting-settings-title">Meeting Recorder</h2>

            {/* GPU Acceleration */}
            <div className="meeting-settings-section">
                <div className="meeting-settings-label">GPU Acceleration</div>
                <div className="meeting-settings-gpu-display">
                    <span className={`gpu-badge ${computeInfo?.backend === 'cuda' ? 'gpu-cuda' : 'gpu-cpu'}`}>
                        {computeInfo?.backend === 'cuda' ? '⚡' : '🖥️'}
                    </span>
                    <span className="gpu-label">{gpuLabel}</span>
                </div>
                <p className="meeting-settings-hint">
                    Detected automatically. CUDA provides the fastest transcription.
                </p>
            </div>

            {/* Live Transcription Model */}
            <div className="meeting-settings-section">
                <div className="meeting-settings-label">Live Transcription Model</div>
                <select
                    className="meeting-settings-select"
                    value={settings.whisper_model}
                    onChange={(e) => updateSetting('whisper_model', e.target.value)}
                >
                    <option value="tiny">Tiny — Fastest, least accurate</option>
                    <option value="base">Base — Balanced (recommended)</option>
                    <option value="small">Small — Most accurate, slower</option>
                </select>
                <p className="meeting-settings-hint">
                    Model used for live transcription during recording. Changes apply to the next recording.
                </p>
            </div>

            {/* Speaker Diarization */}
            <div className="meeting-settings-section">
                <div className="meeting-settings-label">Speaker Diarization</div>
                <label className="meeting-settings-toggle">
                    <input
                        type="checkbox"
                        checked={settings.diarization_enabled === 'true'}
                        onChange={(e) =>
                            updateSetting('diarization_enabled', e.target.checked ? 'true' : 'false')
                        }
                    />
                    <span className="toggle-slider"></span>
                    <span className="toggle-label">
                        {settings.diarization_enabled === 'true' ? 'Enabled' : 'Disabled'}
                    </span>
                </label>
                <p className="meeting-settings-hint">
                    Identifies different speakers in the transcript (Speaker 1, Speaker 2, etc.).
                    Disabling speeds up post-processing.
                </p>
            </div>

            {/* Keep Raw Audio */}
            <div className="meeting-settings-section">
                <div className="meeting-settings-label">Keep Raw Audio</div>
                <label className="meeting-settings-toggle">
                    <input
                        type="checkbox"
                        checked={settings.keep_audio === 'true'}
                        onChange={(e) =>
                            updateSetting('keep_audio', e.target.checked ? 'true' : 'false')
                        }
                    />
                    <span className="toggle-slider"></span>
                    <span className="toggle-label">
                        {settings.keep_audio === 'true' ? 'Keep files' : 'Delete after processing'}
                    </span>
                </label>
                <p className="meeting-settings-hint">
                    When disabled, audio files are deleted after post-processing to save disk space.
                </p>
            </div>

            {saving && <div className="meeting-settings-saving">Saving...</div>}
        </div>
    );
};

export default MeetingRecorderSettings;
