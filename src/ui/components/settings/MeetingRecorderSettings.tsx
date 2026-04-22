import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { BoltIcon, MonitorIcon } from '../icons/AppIcons';
import { api } from '../../services/api';
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

type HuggingFaceStatus = {
    has_key: boolean;
    masked: string | null;
};

const MeetingRecorderSettings: React.FC = () => {
    const { send, subscribe } = useWebSocket();
    const [computeInfo, setComputeInfo] = useState<ComputeInfo | null>(null);
    const [settings, setSettings] = useState<MeetingSettings>({
        whisper_model: 'base',
        keep_audio: 'false',
        diarization_enabled: 'true',
    });
    const [saving, setSaving] = useState(false);
    const [hfToken, setHfToken] = useState('');
    const [hfStatus, setHfStatus] = useState<HuggingFaceStatus>({
        has_key: false,
        masked: null,
    });
    const [hfBusy, setHfBusy] = useState(false);
    const [hfMessage, setHfMessage] = useState('');
    const [hfError, setHfError] = useState('');

    useEffect(() => {
        let cancelled = false;

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

        void api.getApiKeyStatus().then((status) => {
            if (cancelled) {
                return;
            }
            setHfStatus(status.huggingface ?? { has_key: false, masked: null });
        });

        return () => {
            cancelled = true;
            unsubscribe();
        };
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

    const handleSaveHfToken = async () => {
        const trimmed = hfToken.trim();
        if (!trimmed) {
            setHfError('Enter a Hugging Face token before saving.');
            setHfMessage('');
            return;
        }

        setHfBusy(true);
        setHfError('');
        setHfMessage('');
        try {
            const result = await api.saveApiKey('huggingface', trimmed);
            setHfStatus({ has_key: true, masked: result.masked });
            setHfToken('');
            setHfMessage('Hugging Face token saved.');
        } catch (error) {
            setHfError(error instanceof Error ? error.message : 'Failed to save Hugging Face token.');
        } finally {
            setHfBusy(false);
        }
    };

    const handleRemoveHfToken = async () => {
        setHfBusy(true);
        setHfError('');
        setHfMessage('');
        try {
            await api.deleteApiKey('huggingface');
            setHfStatus({ has_key: false, masked: null });
            setHfToken('');
            setHfMessage('Hugging Face token removed.');
        } catch (error) {
            setHfError(error instanceof Error ? error.message : 'Failed to remove Hugging Face token.');
        } finally {
            setHfBusy(false);
        }
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

            {/* Hugging Face token */}
            <div className="meeting-settings-card">
                <div className="meeting-settings-card-info">
                    <h3 className="meeting-settings-card-title">Hugging Face Token</h3>
                    <p className="meeting-settings-card-description">
                        Required only for speaker diarization. The token is encrypted before it is stored on this machine.
                    </p>
                </div>
                <div className="meeting-settings-token-status">
                    <span className={`meeting-settings-status-badge ${hfStatus.has_key ? 'is-configured' : 'is-missing'}`}>
                        {hfStatus.has_key ? 'Configured' : 'Not configured'}
                    </span>
                    {hfStatus.masked && (
                        <span className="meeting-settings-token-mask">{hfStatus.masked}</span>
                    )}
                </div>
                <label className="meeting-settings-field-label" htmlFor="meeting-hf-token">
                    Personal access token
                </label>
                <input
                    id="meeting-hf-token"
                    className="meeting-settings-input"
                    type="password"
                    placeholder="hf_..."
                    autoComplete="off"
                    value={hfToken}
                    onChange={(e) => setHfToken(e.target.value)}
                />
                <div className="meeting-settings-actions">
                    <button
                        type="button"
                        className="meeting-settings-button"
                        onClick={() => { void handleSaveHfToken(); }}
                        disabled={hfBusy}
                    >
                        {hfBusy ? 'Saving...' : 'Save token'}
                    </button>
                    <button
                        type="button"
                        className="meeting-settings-button meeting-settings-button-secondary"
                        onClick={() => { void handleRemoveHfToken(); }}
                        disabled={hfBusy || !hfStatus.has_key}
                    >
                        Remove token
                    </button>
                </div>
                <div className="meeting-settings-instructions">
                    <p className="meeting-settings-card-description">
                        1. Create a Read token at{' '}
                        <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">
                            huggingface.co/settings/tokens
                        </a>.
                    </p>
                    <p className="meeting-settings-card-description">
                        2. Accept the model licenses for{' '}
                        <a href="https://huggingface.co/pyannote/speaker-diarization-3.1" target="_blank" rel="noreferrer">
                            pyannote/speaker-diarization-3.1
                        </a>{' '}
                        and{' '}
                        <a href="https://huggingface.co/pyannote/segmentation-3.0" target="_blank" rel="noreferrer">
                            pyannote/segmentation-3.0
                        </a>.
                    </p>
                    <p className="meeting-settings-card-description">
                        3. Save the token here, then leave speaker diarization enabled for future recordings.
                    </p>
                </div>
                {hfError && <div className="meeting-settings-error">{hfError}</div>}
                {hfMessage && <div className="meeting-settings-success">{hfMessage}</div>}
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
