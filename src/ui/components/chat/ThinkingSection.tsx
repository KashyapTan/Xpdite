/**
 * Thinking section component.
 * 
 * Shows the model's reasoning process in a collapsible section.
 */
import ReactMarkdown from 'react-markdown';
import { ChevronRightIcon } from '../icons/AppIcons';
import { LoadingDots } from './LoadingDots';

interface ThinkingSectionProps {
  thinking: string;
  isThinking: boolean;
  collapsed: boolean;
  onToggle: () => void;
}

export function ThinkingSection({ thinking, isThinking, collapsed, onToggle }: ThinkingSectionProps) {
  if (!thinking) {
    return null;
  }

  return (
    <div className="thinking-section">
      <div className="thinking-header" onClick={onToggle}>
        <ChevronRightIcon
          size={12}
          className={`thinking-arrow ${collapsed ? '' : 'expanded'}`}
        />
        <span className="thinking-label">
          {isThinking ? 'Thinking...' : 'Thought process'}
        </span>
        {isThinking && <LoadingDots />}
      </div>
      {!collapsed && (
        <div className="thinking-content">
          <ReactMarkdown>{thinking}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
