import { useState, useEffect } from 'react';
import React from 'react';
import ReactMarkdown from 'react-markdown';
import type { ToolCall, ContentBlock } from '../../types';
import { CodeBlock } from './CodeBlock';
import { InlineTerminalBlock } from './InlineTerminalBlock';
import { getHumanReadableDescription, groupBlocks } from './toolCallUtils';
import '../../CSS/InlineTerminal.css';

interface ToolCallsDisplayProps {
  toolCalls: ToolCall[];
}

// ─── Inline single tool card (no outer container) ────────────────────────────

interface InlineToolCardProps {
  toolCall: ToolCall;
}

export function InlineToolCard({ toolCall }: InlineToolCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { badge, text } = getHumanReadableDescription(toolCall);
  const isRunning = toolCall.status === 'calling';

  return (
    <div className="inline-tool-card-wrapper">
      <div
        className={`tool-timeline-item ${isRunning ? 'running' : ''} ${isExpanded ? 'expanded' : ''}`}
        onClick={() => !isRunning && !!toolCall.result && setIsExpanded(!isExpanded)}
        style={!isRunning && !toolCall.result ? { cursor: 'default' } : undefined}
      >
        <div className="tool-status-icon-wrapper">
          {isRunning ? (
            <svg className="tool-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
            </svg>
          ) : (
            <svg className="tool-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          )}
        </div>
        <div className="tool-badge">{badge}</div>
        <div className="tool-desc">{text}</div>
        {!isRunning && !!toolCall.result && (
          <svg
            className={`tool-item-chevron ${isExpanded ? 'expanded' : ''}`}
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        )}
      </div>
      {isExpanded && !isRunning && !!toolCall.result && (
        <div className="tool-details-panel">
          <div className="tool-details-label">Result:</div>
          <pre className="tool-details-content">{toolCall.result}</pre>
        </div>
      )}
    </div>
  );
}

// ─── Inline content-block renderer (shared by ChatMessage & ResponseArea) ─────

interface InlineContentBlocksProps {
  blocks: ContentBlock[];
  onTerminalApprove?: (requestId: string) => void;
  onTerminalDeny?: (requestId: string) => void;
  onTerminalApproveRemember?: (requestId: string) => void;
  onTerminalKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
}

export function InlineContentBlocks({
  blocks,
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
}: InlineContentBlocksProps) {
  const groups = groupBlocks(blocks);

  return (
    <>
      {groups.map((g, idx) => {
        if (g.kind === 'text') {
          return (
            <ReactMarkdown
              key={idx}
              components={{ code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>> }}
            >
              {g.content}
            </ReactMarkdown>
          );
        }
        if (g.kind === 'single_tool') {
          return <InlineToolCard key={idx} toolCall={g.toolCall} />;
        }
        if (g.kind === 'terminal_command') {
          return (
            <InlineTerminalBlock
              key={idx}
              terminal={g.terminal}
              onApprove={onTerminalApprove}
              onDeny={onTerminalDeny}
              onApproveRemember={onTerminalApproveRemember}
              onKill={onTerminalKill}
              onTerminalResize={onTerminalResize}
            />
          );
        }
        return <ToolCallsDisplay key={idx} toolCalls={g.toolCalls} />;
      })}
    </>
  );
}

export function ToolCallsDisplay({ toolCalls }: ToolCallsDisplayProps) {
  // State for the main container (all tools)
  const [isMainExpanded, setIsMainExpanded] = useState(false);
  
  // State for individual tool details (keyed by index)
  const [expandedToolIndices, setExpandedToolIndices] = useState<Set<number>>(new Set());

  // Auto-expand main container if tools are active
  useEffect(() => {
    const hasActiveCall = toolCalls.some(tc => tc.status === 'calling');
    if (hasActiveCall) {
      setIsMainExpanded(true);
    }
  }, [toolCalls]);

  if (!toolCalls || toolCalls.length === 0) {
    return null;
  }

  const toggleMain = () => setIsMainExpanded(!isMainExpanded);

  const toggleTool = (index: number) => {
    const newSet = new Set(expandedToolIndices);
    if (newSet.has(index)) {
      newSet.delete(index);
    } else {
      newSet.add(index);
    }
    setExpandedToolIndices(newSet);
  };

  const isAnyRunning = toolCalls.some(tc => tc.status === 'calling');

  return (
    <div className="tool-calls-container-simple">
      {/* Main Collapsible Header */}
      <div 
        className={`tool-main-header ${isMainExpanded ? 'expanded' : ''}`} 
        onClick={toggleMain}
      >
        <div className="tool-main-header-left">
           {isAnyRunning ? (
             <svg className="tool-spinner small" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
             </svg>
           ) : (
             <svg className="tool-icon-static" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
               <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
             </svg>
           )}
           <span>{isAnyRunning ? 'Running Tools' : `Used ${toolCalls.length} tool${toolCalls.length !== 1 ? 's' : ''}`}</span>
        </div>
        
        <svg 
          className={`tool-chevron ${isMainExpanded ? 'expanded' : ''}`} 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          strokeWidth="2"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      {/* Main List */}
      {isMainExpanded && (
        <div className="tool-list-wrapper">
          {toolCalls.map((tc, idx) => {
            const { badge, text } = getHumanReadableDescription(tc);
            const isRunning = tc.status === 'calling';
            const isItemExpanded = expandedToolIndices.has(idx);
            
            return (
              <div key={idx} className="tool-item-container">
                {/* Tool Header (Always Visible) */}
                <div 
                  className={`tool-timeline-item ${isItemExpanded ? 'expanded' : ''} ${isRunning ? 'running' : ''}`}
                  onClick={() => !isRunning && !!tc.result && toggleTool(idx)}
                  style={!isRunning && !tc.result ? { cursor: 'default' } : undefined}
                >
                  <div className="tool-status-icon-wrapper">
                    {isRunning ? (
                      <svg className="tool-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                      </svg>
                    ) : (
                      <svg className="tool-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </div>

                  <div className="tool-badge">{badge}</div>
                  <div className="tool-desc">{text}</div>
                  
                  {!isRunning && !!tc.result && (
                     <svg 
                       className={`tool-item-chevron ${isItemExpanded ? 'expanded' : ''}`} 
                       viewBox="0 0 24 24" 
                       fill="none" 
                       stroke="currentColor" 
                       strokeWidth="2"
                     >
                       <polyline points="6 9 12 15 18 9" />
                     </svg>
                  )}
                </div>

                {/* Tool Details (Expanded) */}
                {isItemExpanded && !isRunning && !!tc.result && (
                  <div className="tool-details-panel">
                    <div className="tool-details-label">Result:</div>
                    <pre className="tool-details-content">
                      {tc.result}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
