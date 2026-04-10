import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { BoltIcon, MonitorIcon } from '../icons/AppIcons';
import '../../CSS/settings/SettingsMeetingRecorder.css';

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
            <div className="meeting-settings-card">
                <div className="meeting-settings-card-info">
                    <h3 className="meeting-settings-card-title">GPU Acceleration</h3>
                    <p className="meeting-settings-card-description">
                        Detected automatically. CUDA provides the fastest transcription.
                    </p>
                </div>
                <div className="meeting-settings-gpu-display">
                    <span className={`gpu-badge ${computeInfo?.backend === 'cuda' ? 'gpu-cuda' : 'gpu-cpu'}`}>
                        {computeInfo?.backend === 'cuda'
                            ? <BoltIcon size={16} />
                            : <MonitorIcon size={16} />}
                    </span>
                    <span className="gpu-label">{gpuLabel}</span>
                </div>
            </div>

            {/* Live Transcription Model */}
            <div className="meeting-settings-card">
                <div className="meeting-settings-card-info">
                    <h3 className="meeting-settings-card-title">Live Transcription Model</h3>
                    <p className="meeting-settings-card-description">
                        Model used for live transcription during recording. Changes apply to the next recording.
                    </p>
                </div>
                <select
                    className="meeting-settings-select"
                    value={settings.whisper_model}
                    onChange={(e) => updateSetting('whisper_model', e.target.value)}
                >
                    <option value="tiny">Tiny | Fastest, least accurate</option>
                    <option value="base">Base | Balanced (recommended)</option>
                    <option value="small">Small | Most accurate, slower</option>
                </select>
            </div>

            {/* Speaker Diarization */}
            <div className="meeting-settings-card">
                <div className="meeting-settings-card-header">
                    <div className="meeting-settings-card-info">
                        <h3 className="meeting-settings-card-title">Speaker Diarization</h3>
                        <p className="meeting-settings-card-description">
                            Identifies different speakers in the transcript. Disabling speeds up post-processing.
                        </p>
                    </div>
                    <label className="meeting-settings-toggle">
                        <input
                            type="checkbox"
                            checked={settings.diarization_enabled === 'true'}
                            onChange={(e) =>
                                updateSetting('diarization_enabled', e.target.checked ? 'true' : 'false')
                            }
                        />
                        <span className="meeting-settings-toggle-slider"></span>
                    </label>
                </div>
            </div>

            {/* Keep Raw Audio */}
            <div className="meeting-settings-card">
                <div className="meeting-settings-card-header">
                    <div className="meeting-settings-card-info">
                        <h3 className="meeting-settings-card-title">Keep Raw Audio</h3>
                        <p className="meeting-settings-card-description">
                            When disabled, audio files are deleted after post-processing to save disk space.
                        </p>
                    </div>
                    <label className="meeting-settings-toggle">
                        <input
                            type="checkbox"
                            checked={settings.keep_audio === 'true'}
                            onChange={(e) =>
                                updateSetting('keep_audio', e.target.checked ? 'true' : 'false')
                            }
                        />
                        <span className="meeting-settings-toggle-slider"></span>
                    </label>
                </div>
            </div>

            {saving && <div className="meeting-settings-saving">Saving...</div>}
        </div>
    );
};

export default MeetingRecorderSettings;
