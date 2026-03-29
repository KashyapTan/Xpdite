/**
 * Response area component.
 * 
 * Container for chat history and current streaming response.
 */
import React from 'react';
import { ChatMessage } from './ChatMessage';
import { LoadingDots } from './LoadingDots';
import { InlineContentBlocks } from './ToolCallsDisplay';
import type { ChatMessage as ChatMessageType, ContentBlock } from '../../types';
import { buildRenderableContentBlocks } from '../../utils/chatMessages';

interface ResponseAreaProps {
  chatHistory: ChatMessageType[];
  currentQuery: string;
  thinking: string;
  isThinking: boolean;
  thinkingCollapsed: boolean;
  contentBlocks?: ContentBlock[];
  generatingModel: string;
  canSubmit: boolean;
  error: string;
  showScrollBottom: boolean;
  onRetryMessage: (message: ChatMessageType) => void;
  onEditMessage: (message: ChatMessageType, content: string) => void;
  onSetActiveResponse: (message: ChatMessageType, responseIndex: number) => void;
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
  onYouTubeApprovalResponse?: (requestId: string, approved: boolean) => void;
  hasTabBar: boolean;
  topInset: number;
  bottomInset: number;
  scrollButtonBottom: number;
}

export function ResponseArea({
  chatHistory,
  currentQuery,
  thinking,
  isThinking,
  thinkingCollapsed,
  contentBlocks,
  generatingModel,
  canSubmit,
  error,
  showScrollBottom,
  onRetryMessage,
  onEditMessage,
  onSetActiveResponse,
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
  onYouTubeApprovalResponse,
  hasTabBar,
  topInset,
  bottomInset,
  scrollButtonBottom,
}: ResponseAreaProps) {
  const liveBlocks = buildRenderableContentBlocks({
    content: '',
    thinking,
    contentBlocks,
  });
  const hasContentBlocks = !!liveBlocks && liveBlocks.length > 0;
  const isSingleThinkingTimeline = !!liveBlocks
    && liveBlocks.length === 1
    && liveBlocks[0].type === 'thinking';
  const responseAreaStyle = {
    marginTop: hasTabBar ? 0 : `${topInset}px`,
    marginBottom: `${bottomInset}px`,
    height: `calc(100% - ${topInset + bottomInset}px)`,
  };
  const scrollButtonStyle = {
    bottom: `${scrollButtonBottom}px`,
  };

  return (
    <>
      <div className="response-area" ref={responseAreaRef} onScroll={onScroll} style={responseAreaStyle}>
        {error && (
          <div className="error">
            <strong>Error:</strong> {error}
          </div>
        )}

        {/* Chat history */}
        {!error &&
          chatHistory.map((msg, idx) => (
            <ChatMessage
              key={msg.messageId ?? `${msg.role}-${idx}`}
              message={msg}
              selectedModel={generatingModel}
              actionsDisabled={!canSubmit}
              onRetryMessage={onRetryMessage}
              onEditMessage={onEditMessage}
              onSetActiveResponse={onSetActiveResponse}
            />
          ))}

        {/* Current query being processed */}
        {!error && currentQuery && !canSubmit && (
          <div className="query">
            <p>{currentQuery}</p>
          </div>
        )}

        {/* Loading animation while waiting for first content */}
        <LoadingDots isVisible={!error && !canSubmit && !thinking && !hasContentBlocks} />

        {/* Live inline content blocks (text interleaved with tool calls) */}
        {!error && hasContentBlocks && (
          <div className="response">
            <div className="assistant-header">Xpdite • {generatingModel}</div>
            <InlineContentBlocks
              blocks={liveBlocks!}
              isThinking={isThinking}
              isStreaming={!canSubmit}
              expanded={isSingleThinkingTimeline ? !thinkingCollapsed : undefined}
              onToggleExpanded={isSingleThinkingTimeline ? onToggleThinking : undefined}
              onTerminalApprove={onTerminalApprove}
              onTerminalDeny={onTerminalDeny}
              onTerminalApproveRemember={onTerminalApproveRemember}
              onTerminalKill={onTerminalKill}
              onTerminalResize={onTerminalResize}
              onYouTubeApprovalResponse={onYouTubeApprovalResponse}
            />
          </div>
        )}
      </div>

      {showScrollBottom && (
        <button
          className="scroll-bottom-button"
          onClick={onScrollToBottom}
          title="Scroll to bottom"
          style={scrollButtonStyle}
        >
          <img src={scrollDownIcon} alt="Scroll down" className="scroll-down-icon" />
        </button>
      )}
    </>
  );
}
