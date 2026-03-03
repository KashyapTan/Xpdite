/**
 * Chat message component.
 * 
 * Renders a single chat message (user or assistant).
 */
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { CodeBlock } from './CodeBlock';
import { ThinkingSection } from './ThinkingSection';
import { ToolCallsDisplay, InlineContentBlocks } from './ToolCallsDisplay';
import type { ChatMessage as ChatMessageType } from '../../types';

interface ChatMessageProps {
  message: ChatMessageType;
  selectedModel: string;
}

export function ChatMessage({ message, selectedModel }: ChatMessageProps) {
  const [thinkingCollapsed, setThinkingCollapsed] = useState(true);

  return (
    <div className={message.role === 'user' ? 'chat-user' : 'chat-assistant'}>
      {/* Historical thinking section rendered ABOVE the response bubble */}
      {message.role === 'assistant' && message.thinking && (
        <ThinkingSection
          thinking={message.thinking}
          isThinking={false}
          collapsed={thinkingCollapsed}
          onToggle={() => setThinkingCollapsed(prev => !prev)}
        />
      )}
      <div className={message.role === 'user' ? 'query' : 'response'}>
        {message.role === 'assistant' && (
          <div className="assistant-header">Xpdite • {message.model || selectedModel}</div>
        )}
        <div className="message-content">
          {message.role === 'user' ? (
            <div className="user-text">
              {message.content.split(/(\/\w+)/g).map((part, i) => {
                if (part.startsWith('/') && part.match(/^\/\w+$/)) {
                  return <code key={i} className="slash-command-history">{part}</code>;
                }
                return part;
              })}
            </div>
          ) : message.contentBlocks && message.contentBlocks.length > 0 ? (
            /* ── Inline interleaved rendering (preferred) ── */
            <InlineContentBlocks blocks={message.contentBlocks} />
          ) : (
            /* ── Legacy fallback: tool calls at top, then text ── */
            <>
              {message.toolCalls && <ToolCallsDisplay toolCalls={message.toolCalls} />}
              <ReactMarkdown components={{ code: CodeBlock as any }}>
                {message.content}
              </ReactMarkdown>
            </>
          )}
        </div>
        {message.images && message.images.length > 0 && (
          <MessageImages images={message.images as any} />
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
            <span className="message-chip-icon">📷</span>
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
