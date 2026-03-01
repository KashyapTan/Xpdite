/**
 * Response area component.
 * 
 * Container for chat history and current streaming response.
 */
import React from 'react';
import { ChatMessage } from './ChatMessage';
import { ThinkingSection } from './ThinkingSection';
import { LoadingDots } from './LoadingDots';
import { InlineContentBlocks } from './ToolCallsDisplay';
import type { ChatMessage as ChatMessageType, ContentBlock } from '../../types';

interface ResponseAreaProps {
  chatHistory: ChatMessageType[];
  currentQuery: string;
  response: string;
  thinking: string;
  isThinking: boolean;
  thinkingCollapsed: boolean;
  contentBlocks?: ContentBlock[];
  generatingModel: string;
  canSubmit: boolean;
  error: string;
  showScrollBottom: boolean;
  onToggleThinking: () => void;
  onScroll: () => void;
  onScrollToBottom: () => void;
  responseAreaRef: React.RefObject<HTMLDivElement | null>;
  scrollDownIcon: string;
  // Terminal callbacks (passed to InlineTerminalBlock via InlineContentBlocks)
  onTerminalApprove?: (requestId: string) => void;
  onTerminalDeny?: (requestId: string) => void;
  onTerminalApproveRemember?: (requestId: string) => void;
  onTerminalKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
}

export function ResponseArea({
  chatHistory,
  currentQuery,
  response: _response,
  thinking,
  isThinking,
  thinkingCollapsed,
  contentBlocks,
  generatingModel,
  canSubmit,
  error,
  showScrollBottom,
  onToggleThinking,
  onScroll,
  onScrollToBottom,
  responseAreaRef,
  scrollDownIcon,
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
}: ResponseAreaProps) {
  const hasContentBlocks = contentBlocks && contentBlocks.length > 0;

  return (
    <>
      <div className="response-area" ref={responseAreaRef} onScroll={onScroll}>
        {error && (
          <div className="error">
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Chat history */}
        {!error &&
          chatHistory.map((msg, idx) => (
            <ChatMessage key={idx} message={msg} selectedModel={generatingModel} />
          ))}

        {/* Current query being processed */}
        {!error && currentQuery && !canSubmit && (
          <div className="query">
            <p>{currentQuery}</p>
          </div>
        )}

        {/* Loading animation while waiting for first content */}
        {!error && !canSubmit && !thinking && !hasContentBlocks && (
          <LoadingDots />
        )}

        {/* Current thinking process */}
        {!error && thinking && (
          <ThinkingSection
            thinking={thinking}
            isThinking={isThinking}
            collapsed={thinkingCollapsed}
            onToggle={onToggleThinking}
          />
        )}

        {/* Live inline content blocks (text interleaved with tool calls) */}
        {!error && hasContentBlocks && (
          <div className="response">
            <div className="assistant-header">Xpdite • {generatingModel}</div>
            <InlineContentBlocks
              blocks={contentBlocks!}
              onTerminalApprove={onTerminalApprove}
              onTerminalDeny={onTerminalDeny}
              onTerminalApproveRemember={onTerminalApproveRemember}
              onTerminalKill={onTerminalKill}
              onTerminalResize={onTerminalResize}
            />
          </div>
        )}
      </div>

      {showScrollBottom && (
        <button
          className="scroll-bottom-button"
          onClick={onScrollToBottom}
          title="Scroll to bottom"
        >
          <img src={scrollDownIcon} alt="Scroll down" className="scroll-down-icon" />
        </button>
      )}
    </>
  );
}
