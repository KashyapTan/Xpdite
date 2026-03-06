import { useState, useEffect } from 'react';
import React from 'react';
import ReactMarkdown from 'react-markdown';
import type { ToolCall, ContentBlock } from '../../types';
import { CodeBlock } from './CodeBlock';
import { InlineTerminalBlock } from './InlineTerminalBlock';
import { getHumanReadableDescription } from './toolCallUtils';
import '../../CSS/InlineTerminal.css';

// ─── SVG Icons ────────────────────────────────────────────────────────────────

function HourglassIcon() {
  return (
    <svg className="chain-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 22h14" />
      <path d="M5 2h14" />
      <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22" />
      <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
    </svg>
  );
}

function WrenchIcon() {
  return (
    <svg className="chain-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={`chain-icon chain-icon-check ${className ?? ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg className="chain-icon chain-icon-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}

function ChevronIcon({ expanded, small }: { expanded: boolean; small?: boolean }) {
  return (
    <svg
      className={`chain-chevron ${expanded ? 'expanded' : ''} ${small ? 'small' : ''}`}
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

// ─── Summary generation ───────────────────────────────────────────────────────

function getChainSummary(toolCalls: ToolCall[]): string {
  if (toolCalls.length === 0) return 'Processing...';

  const isAnyRunning = toolCalls.some(tc => tc.status === 'calling');
  const runningTool = toolCalls.find(tc => tc.status === 'calling');

  // Single tool: use its description directly
  if (toolCalls.length === 1) {
    const { text } = getHumanReadableDescription(toolCalls[0]);
    return text;
  }

  // While running, describe the current tool
  if (isAnyRunning && runningTool) {
    const { text } = getHumanReadableDescription(runningTool);
    return text;
  }

  // Multiple completed tools: describe by server type
  const byServer = new Map<string, ToolCall[]>();
  for (const tc of toolCalls) {
    const list = byServer.get(tc.server) || [];
    list.push(tc);
    byServer.set(tc.server, list);
  }

  const parts: string[] = [];
  for (const [server, tcs] of byServer) {
    if (server === 'filesystem') {
      parts.push(`accessed ${tcs.length} file${tcs.length > 1 ? 's' : ''}`);
    } else if (server === 'websearch') {
      parts.push('searched the web');
    } else if (server === 'terminal') {
      parts.push(`ran ${tcs.length} command${tcs.length > 1 ? 's' : ''}`);
    } else if (server === 'demo') {
      parts.push(`performed ${tcs.length} calculation${tcs.length > 1 ? 's' : ''}`);
    } else {
      parts.push(`used ${server}`);
    }
  }

  if (parts.length === 0) return `Used ${toolCalls.length} tools`;

  const summary = parts.join(', ').replace(/, ([^,]*)$/, ' and $1');
  return summary.charAt(0).toUpperCase() + summary.slice(1);
}

// ─── Collapsible thinking-tokens item inside the chain ─────────────────────────

function ChainThinkingItem({ text }: { text: string }) {
  const [collapsed, setCollapsed] = useState(true);

  return (
    <div className="chain-item-body">
      <div className="chain-tool-header clickable" onClick={() => setCollapsed(!collapsed)}>
        <span className="chain-thought-label">Thought process</span>
        <ChevronIcon expanded={!collapsed} small />
      </div>
      {!collapsed && (
        <div className="chain-thought-content">
          <ReactMarkdown
            components={{ code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>> }}
          >
            {text}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

// ─── Individual Tool Call in Chain ────────────────────────────────────────────

function ToolCallChainItem({ toolCall, isLast }: { toolCall: ToolCall; isLast: boolean }) {
  const [showResult, setShowResult] = useState(false);
  const { badge, text } = getHumanReadableDescription(toolCall);
  const isRunning = toolCall.status === 'calling';
  const hasResult = !isRunning && !!toolCall.result;

  return (
    <div className="chain-item">
      <div className="chain-item-marker">
        <div className="chain-item-dot">
          {isRunning ? <SpinnerIcon /> : <CheckIcon />}
        </div>
        {!isLast && <div className="chain-item-line" />}
      </div>
      <div className="chain-item-body">
        <div
          className={`chain-tool-header ${hasResult ? 'clickable' : ''}`}
          onClick={() => hasResult && setShowResult(!showResult)}
        >
          <span className="chain-tool-badge">{badge}</span>
          <span className="chain-tool-text">{text}</span>
          {hasResult && <ChevronIcon expanded={showResult} small />}
        </div>
        {showResult && toolCall.result && (
          <pre className="chain-tool-result">{toolCall.result}</pre>
        )}
      </div>
    </div>
  );
}

// ─── Tool Chain Timeline ──────────────────────────────────────────────────────

interface ToolChainTimelineProps {
  blocks: ContentBlock[];
  onTerminalApprove?: (requestId: string) => void;
  onTerminalDeny?: (requestId: string) => void;
  onTerminalApproveRemember?: (requestId: string) => void;
  onTerminalKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
}

function ToolChainTimeline({
  blocks,
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
}: ToolChainTimelineProps) {
  // Find last "chain" block: tool_call, thinking, or terminal_command.
  // Everything up to it stays in the chain; trailing text blocks are the response.
  let lastChainIndex = -1;
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i];
    if (b.type === 'tool_call' || b.type === 'thinking' || b.type === 'terminal_command') {
      lastChainIndex = i;
      break;
    }
  }

  const chainBlocks = lastChainIndex >= 0 ? blocks.slice(0, lastChainIndex + 1) : [];
  const responseBlocks = lastChainIndex >= 0 ? blocks.slice(lastChainIndex + 1) : blocks;

  const toolCalls = chainBlocks
    .filter((b): b is { type: 'tool_call'; toolCall: ToolCall } => b.type === 'tool_call')
    .map(b => b.toolCall);

  const isAnyRunning = toolCalls.some(tc => tc.status === 'calling');
  const allDone = toolCalls.length > 0 && !isAnyRunning;
  const [expanded, setExpanded] = useState(isAnyRunning);

  // Auto-expand while tools are running
  useEffect(() => {
    if (isAnyRunning) setExpanded(true);
  }, [isAnyRunning]);

  // Build the flat list of timeline items
  const timelineItems: Array<
    | { kind: 'thinking_tokens'; text: string }
    | { kind: 'thinking'; content: string }
    | { kind: 'tool'; toolCall: ToolCall }
    | { kind: 'terminal'; terminal: ContentBlock & { type: 'terminal_command' } }
    | { kind: 'done' }
  > = [];

  for (const block of chainBlocks) {
    if (block.type === 'thinking' && block.content.trim()) {
      // Model's internal reasoning tokens — collapsible with markdown rendering
      timelineItems.push({ kind: 'thinking_tokens', text: block.content });
    } else if (block.type === 'text' && block.content.trim()) {
      // Model's visible preamble text between tool calls
      timelineItems.push({ kind: 'thinking', content: block.content });
    } else if (block.type === 'tool_call') {
      timelineItems.push({ kind: 'tool', toolCall: block.toolCall });
    } else if (block.type === 'terminal_command') {
      timelineItems.push({ kind: 'terminal', terminal: block as ContentBlock & { type: 'terminal_command' } });
    }
  }
  if (allDone) {
    timelineItems.push({ kind: 'done' });
  }

  const summary = getChainSummary(toolCalls);

  return (
    <>
      {/* Chain section */}
      {chainBlocks.length > 0 && (
        <div className="tool-chain">
          <div className="tool-chain-header" onClick={() => setExpanded(!expanded)}>
            <div className="tool-chain-header-icon">
              {isAnyRunning ? <SpinnerIcon /> : <CheckIcon />}
            </div>
            <span className="tool-chain-summary" title={summary}>{summary}</span>
            <ChevronIcon expanded={expanded} />
          </div>

          {expanded && (
            <div className="tool-chain-timeline">
              {timelineItems.map((item, idx) => {
                const isLast = idx === timelineItems.length - 1;

                if (item.kind === 'thinking_tokens') {
                  return (
                    <div key={idx} className="chain-item">
                      <div className="chain-item-marker">
                        <div className="chain-item-dot">
                          <HourglassIcon />
                        </div>
                        {!isLast && <div className="chain-item-line" />}
                      </div>
                      <ChainThinkingItem text={item.text} />
                    </div>
                  );
                }

                if (item.kind === 'thinking') {
                  return (
                    <div key={idx} className="chain-item">
                      <div className="chain-item-marker">
                        <div className="chain-item-dot">
                          <HourglassIcon />
                        </div>
                        {!isLast && <div className="chain-item-line" />}
                      </div>
                      <div className="chain-item-body chain-thinking-text">
                        {item.content}
                      </div>
                    </div>
                  );
                }

                if (item.kind === 'tool') {
                  return (
                    <ToolCallChainItem
                      key={idx}
                      toolCall={item.toolCall}
                      isLast={isLast}
                    />
                  );
                }

                if (item.kind === 'terminal') {
                  return (
                    <div key={idx} className="chain-item chain-item-terminal">
                      <div className="chain-item-marker">
                        <div className="chain-item-dot">
                          <WrenchIcon />
                        </div>
                        {!isLast && <div className="chain-item-line" />}
                      </div>
                      <div className="chain-item-body">
                        <InlineTerminalBlock
                          terminal={item.terminal.terminal}
                          onApprove={onTerminalApprove}
                          onDeny={onTerminalDeny}
                          onApproveRemember={onTerminalApproveRemember}
                          onKill={onTerminalKill}
                          onTerminalResize={onTerminalResize}
                        />
                      </div>
                    </div>
                  );
                }

                if (item.kind === 'done') {
                  return (
                    <div key={idx} className="chain-item">
                      <div className="chain-item-marker">
                        <div className="chain-item-dot">
                          <CheckIcon />
                        </div>
                      </div>
                      <div className="chain-item-body chain-done-text">Done</div>
                    </div>
                  );
                }

                return null;
              })}
            </div>
          )}
        </div>
      )}

      {/* Response text (after all tool calls) */}
      {responseBlocks.map((block, idx) => {
        if (block.type === 'text' && block.content.trim()) {
          return (
            <ReactMarkdown
              key={`resp-${idx}`}
              components={{ code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>> }}
            >
              {block.content}
            </ReactMarkdown>
          );
        }
        if (block.type === 'terminal_command') {
          return (
            <InlineTerminalBlock
              key={`resp-${idx}`}
              terminal={block.terminal}
              onApprove={onTerminalApprove}
              onDeny={onTerminalDeny}
              onApproveRemember={onTerminalApproveRemember}
              onKill={onTerminalKill}
              onTerminalResize={onTerminalResize}
            />
          );
        }
        return null;
      })}
    </>
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
  const hasToolCalls = blocks.some(b => b.type === 'tool_call');

  if (hasToolCalls) {
    return (
      <ToolChainTimeline
        blocks={blocks}
        onTerminalApprove={onTerminalApprove}
        onTerminalDeny={onTerminalDeny}
        onTerminalApproveRemember={onTerminalApproveRemember}
        onTerminalKill={onTerminalKill}
        onTerminalResize={onTerminalResize}
      />
    );
  }

  // No tool calls — render text and terminals normally
  return (
    <>
      {blocks.map((block, idx) => {
        if (block.type === 'text' && block.content.trim()) {
          return (
            <ReactMarkdown
              key={idx}
              components={{ code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>> }}
            >
              {block.content}
            </ReactMarkdown>
          );
        }
        if (block.type === 'terminal_command') {
          return (
            <InlineTerminalBlock
              key={idx}
              terminal={block.terminal}
              onApprove={onTerminalApprove}
              onDeny={onTerminalDeny}
              onApproveRemember={onTerminalApproveRemember}
              onKill={onTerminalKill}
              onTerminalResize={onTerminalResize}
            />
          );
        }
        return null;
      })}
    </>
  );
}

// ─── Legacy ToolCallsDisplay (for messages with toolCalls array) ──────────────

interface ToolCallsDisplayProps {
  toolCalls: ToolCall[];
}

export function ToolCallsDisplay({ toolCalls }: ToolCallsDisplayProps) {
  if (!toolCalls || toolCalls.length === 0) return null;

  const blocks: ContentBlock[] = toolCalls.map(tc => ({
    type: 'tool_call' as const,
    toolCall: tc,
  }));
  return <ToolChainTimeline blocks={blocks} />;
}
