import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import type { Skill } from '../../types';
import '../../CSS/settings/SettingsSkills.css';

function getErrorMessage(error: unknown, fallback: string): string {
    return error instanceof Error ? error.message : fallback;
}

const SettingsSkills: React.FC = () => {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [loading, setLoading] = useState(true);
    const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
    const [isCreating, setIsCreating] = useState(false);

    // Editor state
    const [editName, setEditName] = useState('');
    const [editDescription, setEditDescription] = useState('');
    const [editCommand, setEditCommand] = useState('');
    const [editContent, setEditContent] = useState('');
    const [editTriggerServers, setEditTriggerServers] = useState('');
    const [editError, setEditError] = useState('');

    const loadSkills = async () => {
        try {
            setLoading(true);
            const data = await api.skillsApi.getAll();
            setSkills(data);
        } catch (e) {
            console.error("Failed to load skills", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadSkills();
    }, []);

    const handleToggle = async (skill: Skill) => {
        try {
            const newEnabled = !skill.enabled;
            await api.skillsApi.toggle(skill.name, newEnabled);
            setSkills(prev => prev.map(s => s.name === skill.name ? { ...s, enabled: newEnabled } : s));
        } catch (error: unknown) {
            console.error("Failed to toggle skill", error);
            alert(getErrorMessage(error, "Failed to toggle skill"));
        }
    };

    const startEdit = async (skill: Skill | null) => {
        if (skill) {
            setEditingSkill(skill);
            setIsCreating(false);
            setEditName(skill.name);
            setEditDescription(skill.description);
            setEditCommand(skill.slash_command || '');
            setEditTriggerServers(skill.trigger_servers.join(', '));
            // Fetch full content
            try {
                const content = await api.skillsApi.getContent(skill.name);
                setEditContent(content);
            } catch {
                setEditContent('');
            }
        } else {
            setEditingSkill(null);
            setIsCreating(true);
            setEditName('');
            setEditDescription('');
            setEditCommand('');
            setEditContent('');
            setEditTriggerServers('');
        }
        setEditError('');
    };

    const handleSave = async () => {
        setEditError('');
        if (!editDescription.trim() || !editContent.trim()) {
            setEditError("Description and content are required.");
            return;
        }

        const triggerServers = editTriggerServers
            .split(',')
            .map(s => s.trim())
            .filter(Boolean);

        try {
            if (editingSkill) {
                await api.skillsApi.update(editingSkill.name, {
                    description: editDescription,
                    slash_command: editCommand.replace(/^\//, '') || undefined,
                    content: editContent,
                    trigger_servers: triggerServers,
                });
            } else {
                if (!editName.trim()) {
                    setEditError("Name is required for new skills.");
                    return;
                }
                await api.skillsApi.create({
                    name: editName.replace(/[^a-zA-Z0-9_-]/g, '').toLowerCase(),
                    description: editDescription,
                    slash_command: editCommand.replace(/^\//, '') || undefined,
                    content: editContent,
                    trigger_servers: triggerServers,
                });
            }
            await loadSkills();
            setEditingSkill(null);
            setIsCreating(false);
        } catch (error: unknown) {
            setEditError(getErrorMessage(error, "Failed to save skill"));
        }
    };

    const handleDelete = async (name: string) => {
        if (!confirm(`Are you sure you want to delete the "${name}" skill?`)) return;
        try {
            await api.skillsApi.delete(name);
            await loadSkills();
        } catch (error: unknown) {
            alert(getErrorMessage(error, "Failed to delete skill"));
        }
    };

    if (loading && skills.length === 0) {
        return <div className="settings-skills-loading">Loading skills...</div>;
    }

    return (
        <div className="settings-skills-container">
            <div className="settings-skills-header">
                <div>
                    <h2>Skills</h2>
                    <p>Behavioral rules injected into Xpdite's prompt when certain tools are used or slash commands are typed.</p>
                </div>
                {(!isCreating && !editingSkill) && (
                    <button className="create-skill-btn" onClick={() => startEdit(null)}>
                        Add Custom Skill
                    </button>
                )}
            </div>

            {(isCreating || editingSkill) ? (
                <div className="skill-editor" key="editor">
                    <div className="editor-header">
                        <h3>{editingSkill ? `Edit ${editingSkill.description}` : 'Create New Skill'}</h3>
                        <button className="editor-close-btn" onClick={() => { setEditingSkill(null); setIsCreating(false); }}>Cancel</button>
                    </div>

                    {editError && <div className="editor-error">{editError}</div>}

                    <div className="editor-row">
                        <div className="editor-group">
                            <label>Description</label>
                            <input
                                type="text"
                                value={editDescription}
                                onChange={e => setEditDescription(e.target.value)}
                                placeholder="e.g. Guidance for terminal command execution"
                            />
                        </div>
                        <div className="editor-group">
                            <label>Slash Command</label>
                            <div className="input-with-prefix">
                                <span className="prefix">/</span>
                                <input
                                    type="text"
                                    value={editCommand}
                                    onChange={e => setEditCommand(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))}
                                    placeholder="e.g. terminal"
                                />
                            </div>
                        </div>
                    </div>

                    {!editingSkill && (
                        <div className="editor-group">
                            <label>Skill Name (unique identifier, must match folder name)</label>
                            <input
                                type="text"
                                value={editName}
                                onChange={e => setEditName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))}
                                placeholder="e.g. my-custom-skill"
                            />
                        </div>
                    )}

                    <div className="editor-group">
                        <label>Trigger Servers (comma-separated MCP server names for auto-detection)</label>
                        <input
                            type="text"
                            value={editTriggerServers}
                            onChange={e => setEditTriggerServers(e.target.value)}
                            placeholder="e.g. terminal, filesystem"
                        />
                    </div>

                    <div className="editor-group">
                        <label>Prompt Content (Markdown supported)</label>
                        <textarea
                            value={editContent}
                            onChange={e => setEditContent(e.target.value)}
                            placeholder="Instructions to inject into the system prompt..."
                            rows={10}
                        />
                    </div>

                    <div className="editor-actions">
                        <button className="save-btn" onClick={handleSave}>Save Skill</button>
                    </div>
                </div>
            ) : (
                <div className="skills-list">
                    {skills.map(skill => (
                        <div key={`${skill.name}-${skill.source}`} className={`skill-card ${!skill.enabled ? 'disabled' : ''}`}>
                            <div className="skill-card-header">
                                <div className="skill-header-left">
                                    <h3 className="skill-name">{skill.name}</h3>
                                    {skill.trigger_servers.length > 0 && (
                                        <span className="skill-triggers">
                                            Triggers: {skill.trigger_servers.join(', ')}
                                        </span>
                                    )}
                                    <p className="skill-description">{skill.description}</p>
                                </div>

                                <div className="skill-header-right">
                                    <div className="skill-tags">
                                        {skill.slash_command && <span className="skill-command">/{skill.slash_command}</span>}
                                        {skill.source === 'builtin' && <span className="skill-badge default">BUILTIN</span>}
                                        {skill.source === 'user' && <span className="skill-badge custom">CUSTOM</span>}
                                        {skill.overridden_by_user && <span className="skill-badge modified">OVERRIDDEN</span>}
                                    </div>
                                    <label className="settings-toggle">
                                        <input
                                            type="checkbox"
                                            checked={skill.enabled}
                                            onChange={() => handleToggle(skill)}
                                            aria-label={`Toggle ${skill.name}`}
                                        />
                                        <span className="settings-toggle-slider"></span>
                                    </label>
                                </div>
                            </div>

                            <div className="skill-card-footer">
                                <span className="skill-version">v{skill.version}</span>
                                <div className="skill-actions">
                                    {skill.source === 'user' && (
                                        <>
                                            <button onClick={() => startEdit(skill)} className="action-btn edit-btn">Edit</button>
                                            <button onClick={() => handleDelete(skill.name)} className="action-btn delete-btn">Delete</button>
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default SettingsSkills;
