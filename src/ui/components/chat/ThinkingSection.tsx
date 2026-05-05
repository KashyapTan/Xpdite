/**
 * Thinking section component.
 * 
 * Shows the model's reasoning process in a collapsible section.
 */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChevronRightIcon } from '../icons/AppIcons';
import { LoadingDots } from './LoadingDots';
import { formatDurationMs } from '../../utils/timing';

interface ThinkingSectionProps {
  thinking: string;
  isThinking: boolean;
  durationMs?: number;
  collapsed: boolean;
  onToggle: () => void;
}

export function ThinkingSection({ thinking, isThinking, durationMs, collapsed, onToggle }: ThinkingSectionProps) {
  if (!thinking) {
    return null;
  }
  const formattedDuration = formatDurationMs(durationMs);
  const label = isThinking
    ? 'Thinking'
    : `Thought${formattedDuration ? ` ${formattedDuration}` : ''}`;

  return (
    <div className="thinking-section">
      <div className="thinking-header" onClick={onToggle}>
        <ChevronRightIcon
          size={12}
          className={`thinking-arrow ${collapsed ? '' : 'expanded'}`}
        />
        <span className="thinking-label">
          {label}
        </span>
        {isThinking && <LoadingDots />}
      </div>
      {!collapsed && (
        <div className="thinking-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{thinking}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
