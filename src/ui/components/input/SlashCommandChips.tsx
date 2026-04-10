import React from 'react';
import { XIcon } from '../icons/AppIcons';
import '../../CSS/input/SlashCommandChips.css';

interface SlashCommandChipsProps {
    query: string;
    onRemoveCommand: (command: string) => void;
}

/**
 * Displays active slash commands as styled chips above the input.
 * Extracts slash commands from the query text and shows them as removable badges.
 */
const SlashCommandChips: React.FC<SlashCommandChipsProps> = ({ query, onRemoveCommand }) => {
    // Extract all slash commands from the query
    const commands = query.match(/\/[a-zA-Z0-9_-]+/g) || [];

    // Deduplicate
    const uniqueCommands = [...new Set(commands)];

    if (uniqueCommands.length === 0) return null;

    return (
        <div className="slash-command-chips-container">
            {uniqueCommands.map((cmd) => (
                <div key={cmd} className="slash-command-chip">
                    <span className="chip-text">{cmd}</span>
                    <button
                        type="button"
                        className="chip-remove-btn"
                        aria-label={`Remove ${cmd}`}
                        onClick={() => onRemoveCommand(cmd)}
                        title={`Remove ${cmd}`}
                    >
                        <XIcon size={11} />
                    </button>
                </div>
            ))}
        </div>
    );
};

export default SlashCommandChips;
