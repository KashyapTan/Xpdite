/**
 * StreamingTextBlock component.
 *
 * Renders streaming text with a character-drain animation effect.
 * Uses useStreamingAnimation hook to buffer and smoothly render characters.
 *
 * For non-streaming content (history messages), renders instantly without animation.
 */
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';
import { useStreamingAnimation } from '../../hooks/useStreamingAnimation';
import '../../CSS/chat/StreamingAnimation.css';

interface StreamingTextBlockProps {
  /** The raw text content (may be incomplete during streaming) */
  content: string;
  /** Whether this block is currently being streamed */
  isStreaming: boolean;
}

export function StreamingTextBlock({
  content,
  isStreaming,
}: StreamingTextBlockProps) {
  const { displayedText, isDraining } = useStreamingAnimation({
    rawText: content,
    isStreaming,
  });

  const isActivelyStreaming = isStreaming || isDraining;

  // Use displayedText while actively streaming OR still draining characters.
  // Only switch to full content when both streaming has stopped AND drain is complete.
  // This prevents an abrupt "jump" from partial to full text when streaming ends.
  const textToRender = isActivelyStreaming ? displayedText : content;

  // Don't render empty content
  if (!textToRender.trim()) {
    return null;
  }

  return (
    <div className="streaming-text-container">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>>,
        }}
      >
        {textToRender}
      </ReactMarkdown>
    </div>
  );
}
