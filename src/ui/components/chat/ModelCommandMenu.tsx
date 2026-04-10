import React from 'react';
import { formatModelLabel, getModelProviderKey, getProviderLabel } from '../../utils/modelDisplay';
import '../../CSS/chat/ModelCommandMenu.css';

interface ModelCommandMenuProps {
  models: string[];
  selectedIndex: number;
  onHover: (index: number) => void;
  onSelect: (model: string) => void;
  position: { top: number; left: number };
}

const ModelCommandMenu: React.FC<ModelCommandMenuProps> = ({
  models,
  selectedIndex,
  onHover,
  onSelect,
  position,
}) => {
  if (models.length === 0) {
    return null;
  }

  return (
    <div
      className="model-command-menu"
      style={{
        bottom: 'calc(100% + 10px)',
        left: `${position.left}px`,
      }}
      onMouseDown={(event) => {
        event.preventDefault();
      }}
    >
      <div className="model-menu-header">Models</div>
      <div className="model-menu-list">
        {models.map((model, index) => {
          const label = formatModelLabel(model);
          const providerKey = getModelProviderKey(model);
          const providerLabel = getProviderLabel(providerKey);

          return (
            <button
              key={model}
              type="button"
              className={`model-menu-item ${index === selectedIndex ? 'selected' : ''}`}
              onClick={() => onSelect(model)}
              onMouseEnter={() => onHover(index)}
            >
              <span className="model-menu-name">{label}</span>
              <span className="model-menu-provider">{providerLabel}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default ModelCommandMenu;
