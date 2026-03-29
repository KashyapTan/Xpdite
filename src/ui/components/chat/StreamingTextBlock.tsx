/**
 * StreamingTextBlock component.
 *
 * Renders streaming text with a character-drain animation effect.
 * Uses useStreamingAnimation hook to buffer and smoothly render characters,
 * and displays an animated cursor at the end while streaming is active.
 *
 * For non-streaming content (history messages), renders instantly without animation.
 */
import React from 'react';
import ReactMarkdown from 'react-markdown';
import { CodeBlock } from './CodeBlock';
import { useStreamingAnimation } from '../../hooks/useStreamingAnimation';
import '../../CSS/StreamingAnimation.css';

interface StreamingTextBlockProps {
  /** The raw text content (may be incomplete during streaming) */
  content: string;
  /** Whether this block is currently being streamed */
  isStreaming: boolean;
  /** Whether this is a thinking block (affects cursor styling) */
  isThinking?: boolean;
}

export function StreamingTextBlock({
  content,
  isStreaming,
  isThinking = false,
}: StreamingTextBlockProps) {
  const { displayedText, isDraining } = useStreamingAnimation({
    rawText: content,
    isStreaming,
  });

  // Show cursor while streaming or still draining characters
  const showCursor = isStreaming || isDraining;

  // Use displayedText while actively streaming OR still draining characters.
  // Only switch to full content when both streaming has stopped AND drain is complete.
  // This prevents an abrupt "jump" from partial to full text when streaming ends.
  const textToRender = (isStreaming || isDraining) ? displayedText : content;

  // Don't render empty content
  if (!textToRender.trim()) {
    return null;
  }

  const cursorClassName = `streaming-cursor${isThinking ? ' streaming-cursor--thinking' : ''}`;

  return (
    <div className="streaming-text-container">
      <ReactMarkdown
        components={{
          code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>>,
        }}
      >
        {textToRender}
      </ReactMarkdown>
      {showCursor && <span className={cursorClassName} aria-hidden="true" />}
    </div>
  );
}
