/**
 * Chat message component.
 *
 * Renders a single chat message (user or assistant).
 */
import { useEffect, useState } from 'react';
import type { ComponentPropsWithRef, ComponentType, KeyboardEvent as ReactKeyboardEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import { CodeBlock } from './CodeBlock';
import { InlineContentBlocks } from './ToolCallsDisplay';
import { copyToClipboard } from '../../utils/clipboard';
import {
  buildRenderableContentBlocks,
  formatMessageTimestamp,
  serializeMessageForCopy,
} from '../../utils/chatMessages';
import type { ChatMessage as ChatMessageType } from '../../types';

interface ChatMessageProps {
  message: ChatMessageType;
  selectedModel: string;
  actionsDisabled: boolean;
  onRetryMessage: (message: ChatMessageType) => void;
  onEditMessage: (message: ChatMessageType, content: string) => void;
  onSetActiveResponse: (message: ChatMessageType, responseIndex: number) => void;
}

interface ActionButtonProps {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}

function ActionButton({ title, onClick, disabled = false, children }: ActionButtonProps) {
  return (
    <button
      type="button"
      className="message-footer-button"
      onClick={onClick}
      title={title}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
      <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />
    </svg>
  );
}

function RetryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </svg>
  );
}

function ArrowLeftIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m15 18-6-6 6-6" />
    </svg>
  );
}

function ArrowRightIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

export function ChatMessage({
  message,
  selectedModel,
  actionsDisabled,
  onRetryMessage,
  onEditMessage,
  onSetActiveResponse,
}: ChatMessageProps) {
  const [thinkingCollapsed, setThinkingCollapsed] = useState(true);
  const [isEditing, setIsEditing] = useState(false);
  const [draftContent, setDraftContent] = useState(message.content);

  useEffect(() => {
    if (!isEditing) {
      setDraftContent(message.content);
    }
  }, [isEditing, message.content]);

  const activeResponseIndex = Math.min(
    message.activeResponseIndex ?? 0,
    Math.max((message.responseVersions?.length ?? 1) - 1, 0),
  );
  const formattedTimestamp = formatMessageTimestamp(message.timestamp);
  const canPersistActions = !!message.messageId;
  const canSaveEdit = draftContent.trim().length > 0 && draftContent.trim() !== message.content.trim();
  const renderableBlocks = buildRenderableContentBlocks(message);
  const canControlThoughtTimeline = !!renderableBlocks
    && renderableBlocks.some((block) => block.type === 'thinking')
    && !renderableBlocks.some(
      (block) =>
        block.type === 'tool_call'
        || block.type === 'terminal_command'
        || block.type === 'youtube_transcription_approval',
    );
  const footerClassName =
    message.role === 'user'
      ? 'message-footer message-footer-user'
      : 'message-footer message-footer-assistant';

  const handleSaveEdit = () => {
    const nextContent = draftContent.trim();
    if (!canSaveEdit) {
      return;
    }
    onEditMessage(message, nextContent);
    setIsEditing(false);
  };

  const handleEditKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      setDraftContent(message.content);
      setIsEditing(false);
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      handleSaveEdit();
    }
  };

  const renderUserContent = () => {
    if (isEditing) {
      return (
        <div className="message-edit-container">
          <textarea
            className="message-edit-input"
            value={draftContent}
            onChange={(event) => setDraftContent(event.target.value)}
            onKeyDown={handleEditKeyDown}
            autoFocus
          />
          <div className="message-edit-actions">
            <button
              type="button"
              className="message-edit-button message-edit-cancel"
              onClick={() => {
                setDraftContent(message.content);
                setIsEditing(false);
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="message-edit-button message-edit-save"
              onClick={handleSaveEdit}
              disabled={!canSaveEdit}
            >
              Save
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="user-text">
        {message.content.split(/(\/\w+)/g).map((part, index) => {
          if (part.startsWith('/') && part.match(/^\/\w+$/)) {
            return <code key={index} className="slash-command-history">{part}</code>;
          }
          return part;
        })}
      </div>
    );
  };

  const renderAssistantContent = () => {
    if (renderableBlocks && renderableBlocks.length > 0) {
      return (
        <InlineContentBlocks
          blocks={renderableBlocks}
          expanded={canControlThoughtTimeline ? !thinkingCollapsed : undefined}
          onToggleExpanded={
            canControlThoughtTimeline
              ? () => setThinkingCollapsed((prev) => !prev)
              : undefined
          }
        />
      );
    }

    return (
      <>
        <ReactMarkdown
          components={{
            code: CodeBlock as ComponentType<ComponentPropsWithRef<'code'>>,
          }}
        >
          {message.content}
        </ReactMarkdown>
      </>
    );
  };

  return (
    <div className={message.role === 'user' ? 'chat-user' : 'chat-assistant'}>
      <div className="message-stack">
        <div className={message.role === 'user' ? 'query' : 'response'}>
          {message.role === 'assistant' && (
            <div className="assistant-header">Xpdite • {message.model || selectedModel}</div>
          )}
          <div className="message-content">
            {message.role === 'user' ? renderUserContent() : renderAssistantContent()}
          </div>
          {message.images && message.images.length > 0 && (
            <MessageImages images={message.images} />
          )}
        </div>

        {!isEditing && (
          <div className={footerClassName}>
            {message.role === 'assistant' ? (
              <>
                <ActionButton
                  title="Copy message"
                  onClick={() => {
                    void copyToClipboard(serializeMessageForCopy(message));
                  }}
                >
                  <CopyIcon />
                </ActionButton>
                <ActionButton
                  title="Retry message"
                  onClick={() => onRetryMessage(message)}
                  disabled={actionsDisabled || !canPersistActions}
                >
                  <RetryIcon />
                </ActionButton>
                <span className="message-timestamp">{formattedTimestamp}</span>
                {!!message.responseVersions && message.responseVersions.length > 1 && (
                  <div className="message-response-nav">
                    <ActionButton
                      title="Previous response"
                      onClick={() => onSetActiveResponse(message, activeResponseIndex - 1)}
                      disabled={actionsDisabled || activeResponseIndex <= 0 || !canPersistActions}
                    >
                      <ArrowLeftIcon />
                    </ActionButton>
                    <span className="message-response-index">
                      {activeResponseIndex + 1} / {message.responseVersions.length}
                    </span>
                    <ActionButton
                      title="Next response"
                      onClick={() => onSetActiveResponse(message, activeResponseIndex + 1)}
                      disabled={
                        actionsDisabled ||
                        activeResponseIndex >= message.responseVersions.length - 1 ||
                        !canPersistActions
                      }
                    >
                      <ArrowRightIcon />
                    </ActionButton>
                  </div>
                )}
              </>
            ) : (
              <>
                <span className="message-timestamp">{formattedTimestamp}</span>
                <ActionButton
                  title="Retry message"
                  onClick={() => onRetryMessage(message)}
                  disabled={actionsDisabled || !canPersistActions}
                >
                  <RetryIcon />
                </ActionButton>
                <ActionButton
                  title="Edit message"
                  onClick={() => setIsEditing(true)}
                  disabled={actionsDisabled || !canPersistActions}
                >
                  <EditIcon />
                </ActionButton>
                <ActionButton
                  title="Copy message"
                  onClick={() => {
                    void copyToClipboard(message.content);
                  }}
                >
                  <CopyIcon />
                </ActionButton>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface MessageImagesProps {
  images: Array<{ name: string; thumbnail: string }>;
}

function MessageImages({ images }: MessageImagesProps) {
  return (
    <div className="message-image-chips">
      {images.map((img, idx) => (
        <div key={idx} className="message-image-chip">
          {img.thumbnail ? (
            <img
              src={`data:image/png;base64,${img.thumbnail}`}
              alt={img.name || `Image ${idx + 1}`}
              className="message-chip-thumb"
            />
          ) : (
            <span className="message-chip-icon">[IMG]</span>
          )}
          <span className="message-chip-name">{img.name || `Image ${idx + 1}`}</span>
          {img.thumbnail && (
            <div className="message-chip-hover-preview">
              <img
                src={`data:image/png;base64,${img.thumbnail}`}
                alt={img.name || `Image ${idx + 1}`}
              />
              <span>{img.name || `Image ${idx + 1}`}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
