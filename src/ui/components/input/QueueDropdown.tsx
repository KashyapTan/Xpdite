/**
 * Queue Dropdown — shows queued messages above the input box.
 *
 * Renders a collapsible list of pending queries for the active tab,
 * each with a cancel button.  Hidden when there are no items.
 */
import { useState } from 'react';
import { ChevronRightIcon, XIcon } from '../icons/AppIcons';
import type { QueueItem } from '../../types';

interface QueueDropdownProps {
  items: QueueItem[];
  onCancel: (itemId: string) => void;
}

export function QueueDropdown({ items, onCancel }: QueueDropdownProps) {
  const [expanded, setExpanded] = useState(false);

  if (items.length === 0) return null;

  const nextItem = items[0];
  const queueLabel = items.length === 1 ? 'Queued next' : 'Queued follow-ups';

  return (
    <div className="queue-dropdown">
      <button
        type="button"
        className="queue-dropdown-header"
        onClick={() => setExpanded(prev => !prev)}
        aria-expanded={expanded}
        aria-label={expanded ? 'Collapse queued messages' : 'Expand queued messages'}
      >
        <div className="queue-dropdown-header-copy">
          <span className="queue-dropdown-title">{queueLabel}</span>
          <div className="queue-dropdown-summary">
            <span className="queue-dropdown-order">{nextItem.position}</span>
            <span className="queue-dropdown-preview" title={nextItem.preview}>{nextItem.preview}</span>
          </div>
        </div>
        <ChevronRightIcon
          size={14}
          className={`queue-dropdown-chevron ${expanded ? 'open' : ''}`}
        />
      </button>

      {expanded && (
        <ul className="queue-dropdown-list">
          {items.map((item) => (
            <li key={item.item_id} className="queue-dropdown-item">
              <div className="queue-dropdown-item-copy">
                <span className="queue-dropdown-order">{item.position}</span>
                <span className="queue-dropdown-item-preview" title={item.preview}>{item.preview}</span>
              </div>
              <button
                type="button"
                className="queue-dropdown-cancel"
                onClick={() => onCancel(item.item_id)}
                title="Cancel this queued message"
                aria-label="Cancel this queued message"
              >
                <XIcon size={12} className="queue-dropdown-cancel-icon" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
