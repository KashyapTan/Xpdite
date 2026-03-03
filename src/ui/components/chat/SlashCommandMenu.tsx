import React, { useEffect, useState, useRef } from 'react';
import { api } from '../../services/api';
import type { Skill } from '../../types';
import '../../CSS/SlashCommandMenu.css';

interface SlashCommandMenuProps {
    inputValue: string;
    cursorPosition: number;
    onSelect: (command: string) => void;
    onClose: () => void;
    position: { top: number; left: number };
}

const SlashCommandMenu: React.FC<SlashCommandMenuProps> = ({
    inputValue,
    cursorPosition,
    onSelect,
    onClose,
    position
}) => {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [filteredSkills, setFilteredSkills] = useState<Skill[]>([]);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const menuRef = useRef<HTMLDivElement>(null);

    // Parse the current word at cursor
    const textBeforeCursor = inputValue.slice(0, cursorPosition);
    const currentWordMatch = textBeforeCursor.match(/\/[a-zA-Z0-9_-]*$/);
    const isTriggered = currentWordMatch !== null;
    const searchTerm = currentWordMatch ? currentWordMatch[0].slice(1).toLowerCase() : '';

    useEffect(() => {
        // Only load if triggered
        if (!isTriggered) {
            if (filteredSkills.length > 0) onClose();
            return;
        }

        const loadSkills = async () => {
            try {
                const all = await api.skillsApi.getAll();
                const enabled = all.filter(s => s.enabled && s.slash_command);
                setSkills(enabled);
            } catch (e) {
                console.error("Failed to load skills for slash menu", e);
            }
        };
        if (skills.length === 0) loadSkills();
    }, [isTriggered]);

    useEffect(() => {
        if (!isTriggered) return;

        const filtered = skills.filter(s =>
            (s.slash_command ?? '').toLowerCase().includes(searchTerm) ||
            s.name.toLowerCase().includes(searchTerm)
        );
        setFilteredSkills(filtered);
        setSelectedIndex(0);

        if (filtered.length === 0 && skills.length > 0) {
            onClose(); // Hide if no matches
        }
    }, [searchTerm, skills, isTriggered]);

    // Handle keyboard navigation (intercepted from parent)
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (!isTriggered || filteredSkills.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSelectedIndex(prev => (prev + 1) % filteredSkills.length);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSelectedIndex(prev => (prev - 1 + filteredSkills.length) % filteredSkills.length);
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                onSelect('/' + filteredSkills[selectedIndex].slash_command);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                onClose();
            }
        };

        // We attach to document phase capture to intercept before textarea
        document.addEventListener('keydown', handleKeyDown, true);
        return () => document.removeEventListener('keydown', handleKeyDown, true);
    }, [isTriggered, filteredSkills, selectedIndex, onSelect, onClose]);

    // Click outside listener
    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                onClose();
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [onClose]);

    if (!isTriggered || filteredSkills.length === 0) return null;

    return (
        <div
            ref={menuRef}
            className="slash-command-menu"
            style={{
                bottom: 'calc(100% + 10px)', // Directly above the input
                left: position.left + 'px'
            }}
        >
            <div className="slash-menu-header">Skills</div>
            <div className="slash-menu-list">
                {filteredSkills.map((skill, i) => (
                    <div
                        key={skill.id}
                        className={`slash-menu-item ${i === selectedIndex ? 'selected' : ''}`}
                        onClick={() => onSelect('/' + skill.slash_command)}
                        onMouseEnter={() => setSelectedIndex(i)}
                    >
                        <div className="slash-menu-command">/{skill.slash_command}</div>
                        <div className="slash-menu-name">{skill.name}</div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default SlashCommandMenu;
