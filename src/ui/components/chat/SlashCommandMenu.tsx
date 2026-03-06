import React from 'react';
import type { Skill } from '../../types';
import '../../CSS/SlashCommandMenu.css';

interface SlashCommandMenuProps {
  skills: Skill[];
  selectedIndex: number;
  onHover: (index: number) => void;
  onSelect: (skill: Skill) => void;
  position: { top: number; left: number };
}

const SlashCommandMenu: React.FC<SlashCommandMenuProps> = ({
  skills,
  selectedIndex,
  onHover,
  onSelect,
  position,
}) => {
  if (skills.length === 0) {
    return null;
  }

  return (
    <div
      className="slash-command-menu"
      style={{
        bottom: 'calc(100% + 10px)',
        left: `${position.left}px`,
      }}
      onMouseDown={(event) => {
        event.preventDefault();
      }}
    >
      <div className="slash-menu-header">Skills</div>
      <div className="slash-menu-list">
        {skills.map((skill, index) => (
          <button
            key={skill.name}
            type="button"
            className={`slash-menu-item ${index === selectedIndex ? 'selected' : ''}`}
            onClick={() => onSelect(skill)}
            onMouseEnter={() => onHover(index)}
          >
            <span className="slash-menu-command">/{skill.slash_command}</span>
            <span className="slash-menu-name">{skill.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default SlashCommandMenu;
