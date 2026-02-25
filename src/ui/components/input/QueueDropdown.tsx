/**
 * Queue Dropdown — shows queued messages above the input box.
 *
 * Renders a collapsible list of pending queries for the active tab,
 * each with a cancel button.  Hidden when there are no items.
 */
import { useState } from 'react';
import type { QueueItem } from '../../types';

interface QueueDropdownProps {
  items: QueueItem[];
  onCancel: (itemId: string) => void;
}

export function QueueDropdown({ items, onCancel }: QueueDropdownProps) {
  const [expanded, setExpanded] = useState(true);

  if (items.length === 0) return null;

  return (
    <div className="queue-dropdown">
      <button
        className="queue-dropdown-header"
        onClick={() => setExpanded(prev => !prev)}
        aria-expanded={expanded}
      >
        <span className="queue-dropdown-badge">{items.length}</span>
        <span className="queue-dropdown-label">
          {items.length === 1 ? '1 queued message' : `${items.length} queued messages`}
        </span>
        <span className={`queue-dropdown-chevron ${expanded ? 'open' : ''}`}>›</span>
      </button>

      {expanded && (
        <ul className="queue-dropdown-list">
          {items.map((item) => (
            <li key={item.item_id} className="queue-dropdown-item">
              <span className="queue-dropdown-pos">#{item.position}</span>
              <span className="queue-dropdown-preview">{item.preview}</span>
              <button
                className="queue-dropdown-cancel"
                onClick={() => onCancel(item.item_id)}
                title="Cancel this queued message"
                aria-label="Cancel this queued message"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
