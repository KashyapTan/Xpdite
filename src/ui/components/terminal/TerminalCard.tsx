/**
 * Terminal History Card Component.
 * 
 * Renders collapsed terminal event cards in past conversations.
 * Shows command summary with expand/collapse for output preview.
 */
import { useState } from 'react';
import {
  BanIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  TerminalIcon,
  XIcon,
} from '../icons/AppIcons';
import type { TerminalEvent } from '../../types';

interface TerminalCardProps {
  events: TerminalEvent[];
}

export function TerminalCard({ events }: TerminalCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!events || events.length === 0) return null;

  const totalDuration = events.reduce((sum, e) => sum + e.duration_ms, 0);

  return (
    <div className="terminal-history-card">
      <div
        className="terminal-history-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <TerminalIcon size={14} className="terminal-history-icon" />
        <span className="terminal-history-title">
          Terminal Activity · {events.length} command{events.length !== 1 ? 's' : ''}
          · {(totalDuration / 1000).toFixed(1)}s total
        </span>
        {isExpanded ? (
          <ChevronDownIcon size={10} className="terminal-history-toggle" />
        ) : (
          <ChevronRightIcon size={10} className="terminal-history-toggle" />
        )}
      </div>

      {isExpanded && (
        <div className="terminal-history-body">
          {events.map((event) => (
            <TerminalEventRow key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function TerminalEventRow({ event }: { event: TerminalEvent }) {
  const [showOutput, setShowOutput] = useState(false);

  const EventStatusIcon = event.denied ? BanIcon : event.exit_code === 0 ? CheckIcon : XIcon;
  const iconClass = event.denied
    ? 'denied'
    : event.exit_code === 0
    ? 'success'
    : 'error';

  return (
    <div className="terminal-event-row">
      <div
        className="terminal-event-summary"
        onClick={() => setShowOutput(!showOutput)}
      >
        <EventStatusIcon size={12} className={`terminal-event-icon ${iconClass}`} />
        <span className="terminal-event-command">{event.command}</span>
        <span className="terminal-event-duration">
          {(event.duration_ms / 1000).toFixed(1)}s
        </span>
        {event.pty && <span className="terminal-event-tag">(PTY)</span>}
        {event.timed_out && <span className="terminal-event-tag timeout">(timeout)</span>}
        {event.exit_code !== 0 && !event.denied && (
          <span className="terminal-event-tag error">exit {event.exit_code}</span>
        )}
      </div>

      {showOutput && event.output_preview && (
        <div className="terminal-event-output">
          <pre>{event.output_preview}</pre>
        </div>
      )}
    </div>
  );
}
