/**
 * Response area component.
 * 
 * Container for chat history and current streaming response.
 */
import React, { Suspense, useEffect, useMemo } from 'react';
import { LoadingDots } from './LoadingDots';
import { ChatMessage as ChatMessageView } from './ChatMessage';
import {
  DeferredChatHistory,
  DeferredInlineContentBlocks,
  warmDeferredChatRenderers,
} from './deferredChatRenderers';
import type { ArtifactBlockData, ChatMessage as ChatMessageType, ContentBlock } from '../../types';
import { buildRenderableContentBlocks } from '../../utils/renderableContentBlocks';
import { createChatErrorMessage } from '../../utils/chatErrors';

function LiveContentFallback({
  generatingModel,
  isStreaming,
}: {
  generatingModel: string;
  isStreaming: boolean;
}) {
  return (
    <div className="response">
      <div className="assistant-header">Xpdite • {generatingModel}</div>
      <LoadingDots isVisible={isStreaming} />
    </div>
  );
}

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
  errorMessage?: ChatMessageType | null;
  showScrollBottom: boolean;
  onRetryMessage: (message: ChatMessageType) => void;
  onEditMessage: (message: ChatMessageType, content: string) => void;
  onSetActiveResponse: (message: ChatMessageType, responseIndex: number) => void;
  onArtifactUpdated?: (artifact: ArtifactBlockData) => void;
  onArtifactDeleted?: (artifactId: string) => void;
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

function ResponseAreaComponent({
  chatHistory,
  currentQuery,
  thinking,
  isThinking,
  thinkingCollapsed,
  contentBlocks,
  generatingModel,
  canSubmit,
  error,
  errorMessage,
  showScrollBottom,
  onRetryMessage,
  onEditMessage,
  onSetActiveResponse,
  onArtifactUpdated,
  onArtifactDeleted,
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
  const liveBlocks = useMemo(() => {
    return buildRenderableContentBlocks({
      content: '',
      thinking,
      contentBlocks,
    });
  }, [contentBlocks, thinking]);
  const hasContentBlocks = !!liveBlocks && liveBlocks.length > 0;
  const activeErrorMessage = useMemo(() => {
    if (errorMessage) {
      return errorMessage;
    }
    if (!error) {
      return null;
    }
    return createChatErrorMessage({
      rawError: error,
      source: 'backend',
      model: generatingModel,
    });
  }, [error, errorMessage, generatingModel]);
  const isSingleThinkingTimeline = !!liveBlocks
    && liveBlocks.length === 1
    && liveBlocks[0].type === 'thinking';
  const latestHistoryMessage = chatHistory.length > 0
    ? chatHistory[chatHistory.length - 1]
    : null;
  const hasCommittedCurrentQuery = !!activeErrorMessage
    && !!currentQuery
    && latestHistoryMessage?.role === 'user'
    && latestHistoryMessage.content.trim() === currentQuery.trim();
  const shouldRenderHistory = chatHistory.length > 0;
  const shouldRenderLiveContent = hasContentBlocks;
  const shouldRenderCurrentQuery = !!currentQuery
    && !hasCommittedCurrentQuery
    && (!canSubmit || hasContentBlocks || !!activeErrorMessage);
  const responseAreaStyle = {
    marginTop: hasTabBar ? 0 : `${topInset}px`,
    marginBottom: `${bottomInset}px`,
    height: `calc(100% - ${topInset + bottomInset}px)`,
  };
  const scrollButtonStyle = {
    bottom: `${scrollButtonBottom}px`,
  };

  useEffect(() => {
    const warmRenderers = () => {
      void warmDeferredChatRenderers();
    };

    if (typeof window.requestIdleCallback === 'function') {
      const idleId = window.requestIdleCallback(warmRenderers, { timeout: 1500 });
      return () => {
        window.cancelIdleCallback?.(idleId);
      };
    }

    const timeoutId = window.setTimeout(warmRenderers, 750);
    return () => {
      window.clearTimeout(timeoutId);
    };
  }, []);

  return (
    <>
      <div className="response-area" ref={responseAreaRef} onScroll={onScroll} style={responseAreaStyle}>
        {/* Chat history */}
        {shouldRenderHistory && (
          <Suspense fallback={null}>
            <DeferredChatHistory
              chatHistory={chatHistory}
              generatingModel={generatingModel}
              canSubmit={canSubmit}
              onRetryMessage={onRetryMessage}
              onEditMessage={onEditMessage}
              onSetActiveResponse={onSetActiveResponse}
              onArtifactUpdated={onArtifactUpdated}
              onArtifactDeleted={onArtifactDeleted}
              containerRef={responseAreaRef}
            />
          </Suspense>
        )}

        {/* Current query being processed */}
        {shouldRenderCurrentQuery && (
          <div className="query">
            <p>{currentQuery}</p>
          </div>
        )}

        {/* Loading animation while waiting for first content */}
        <LoadingDots isVisible={!canSubmit && !thinking && !hasContentBlocks} />

        {/* Live inline content blocks (text interleaved with tool calls) */}
        {shouldRenderLiveContent && (
          <Suspense
            fallback={(
              <LiveContentFallback
                generatingModel={generatingModel}
                isStreaming={!canSubmit}
              />
            )}
          >
            <div className="response">
              <div className="assistant-header">Xpdite • {generatingModel}</div>
              <DeferredInlineContentBlocks
                blocks={liveBlocks!}
                isThinking={isThinking}
                isStreaming={!canSubmit}
                expanded={isSingleThinkingTimeline ? !thinkingCollapsed : undefined}
                onToggleExpanded={isSingleThinkingTimeline ? onToggleThinking : undefined}
                onArtifactUpdated={onArtifactUpdated}
                onArtifactDeleted={onArtifactDeleted}
                onTerminalApprove={onTerminalApprove}
                onTerminalDeny={onTerminalDeny}
                onTerminalApproveRemember={onTerminalApproveRemember}
                onTerminalKill={onTerminalKill}
                onTerminalResize={onTerminalResize}
                onYouTubeApprovalResponse={onYouTubeApprovalResponse}
              />
            </div>
          </Suspense>
        )}

        {activeErrorMessage && (
          <ChatMessageView
            message={activeErrorMessage}
            selectedModel={generatingModel}
            actionsDisabled
            onRetryMessage={() => {}}
            onEditMessage={() => {}}
            onSetActiveResponse={() => {}}
          />
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

export const ResponseArea = React.memo(ResponseAreaComponent);
