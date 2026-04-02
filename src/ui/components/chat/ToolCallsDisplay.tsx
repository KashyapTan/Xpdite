import { useState, useEffect, useRef } from 'react';
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ToolCall, ContentBlock } from '../../types';
import { CodeBlock } from './CodeBlock';
import { InlineTerminalBlock } from './InlineTerminalBlock';
import { InlineYouTubeApprovalBlock } from './InlineYouTubeApprovalBlock';
import { SubAgentTranscript } from './SubAgentTranscript';
import { StreamingTextBlock } from './StreamingTextBlock';
import { getHumanReadableDescription, getServerSummaryFragment } from './toolCallUtils';
import '../../CSS/InlineTerminal.css';

// ─── SVG Icons ────────────────────────────────────────────────────────────────

function HourglassIcon() {
  return (
    <svg className="chain-icon chain-icon-hourglass" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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

  const isAnyRunning = toolCalls.some(tc => tc.status === 'calling' || tc.status === 'progress');
  const runningTool = toolCalls.find(tc => tc.status === 'calling' || tc.status === 'progress');

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
    parts.push(getServerSummaryFragment(server, tcs.length));
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
        <span className="chain-thought-label">Thinking...</span>
        <ChevronIcon expanded={!collapsed} small />
      </div>
      {!collapsed && (
        <div className="chain-thought-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
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
  const resultRef = useRef<HTMLDivElement>(null);
  const { badge, text } = getHumanReadableDescription(toolCall);
  const isRunning = toolCall.status === 'calling' || toolCall.status === 'progress';
  const hasResult = !isRunning && !!toolCall.result;
  const isSubAgent = toolCall.server === 'sub_agent';
  // Sub-agents are always expandable while running (to peek at output) or when complete
  const isExpandable = hasResult || (isSubAgent && isRunning);
  const displayContent = hasResult ? toolCall.result : toolCall.partialResult;

  // Auto-scroll the result container when new partial content arrives
  useEffect(() => {
    if (showResult && resultRef.current && isRunning) {
      resultRef.current.scrollTop = resultRef.current.scrollHeight;
    }
  }, [displayContent, showResult, isRunning]);

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
          className={`chain-tool-header ${isExpandable ? 'clickable' : ''}`}
          onClick={() => isExpandable && setShowResult(!showResult)}
        >
          <span className="chain-tool-badge">{badge}</span>
          <span className={`chain-tool-text ${isRunning ? 'running' : ''}`}>{text}</span>
          {isExpandable && <ChevronIcon expanded={showResult} small />}
        </div>
        {showResult && isSubAgent && (
          <div className="chain-tool-result chain-subagent-result" ref={resultRef}>
            <SubAgentTranscript stepsJson={displayContent} isRunning={isRunning} />
          </div>
        )}
        {showResult && !isSubAgent && displayContent && (
          <pre className="chain-tool-result">{displayContent}</pre>
        )}
      </div>
    </div>
  );
}

// ─── Tool Chain Timeline ──────────────────────────────────────────────────────

interface ToolChainTimelineProps {
  blocks: ContentBlock[];
  isThinking?: boolean;
  isStreaming?: boolean;
  expanded?: boolean;
  onToggleExpanded?: () => void;
  onTerminalApprove?: (requestId: string) => void;
  onTerminalDeny?: (requestId: string) => void;
  onTerminalApproveRemember?: (requestId: string) => void;
  onTerminalKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
  onYouTubeApprovalResponse?: (requestId: string, approved: boolean) => void;
}

function ToolChainTimeline({
  blocks,
  isThinking = false,
  isStreaming = false,
  expanded: controlledExpanded,
  onToggleExpanded,
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
  onYouTubeApprovalResponse,
}: ToolChainTimelineProps) {
  // Helper to check if a block is a "chain" block (thinking/tool_call/terminal/youtube_approval)
  const isChainBlock = (b: ContentBlock) =>
    b.type === 'tool_call'
    || b.type === 'thinking'
    || b.type === 'terminal_command'
    || b.type === 'youtube_transcription_approval';

  // Find first and last "chain" block indices.
  // Text BEFORE the first chain block = pre-chain response (render normally above timeline)
  // Text BETWEEN chain blocks = intermediate commentary (render in timeline)
  // Text AFTER the last chain block = final response (render normally below timeline)
  let firstChainIndex = -1;
  let lastChainIndex = -1;
  for (let i = 0; i < blocks.length; i++) {
    if (isChainBlock(blocks[i])) {
      if (firstChainIndex === -1) {
        firstChainIndex = i;
      }
      lastChainIndex = i;
    }
  }

  // Split blocks into three parts:
  // preChainBlocks: text before the first chain block (regular response text)
  // chainBlocks: everything from first to last chain block (timeline content)
  // responseBlocks: text after the last chain block (regular response text)
  const preChainBlocks = firstChainIndex > 0 ? blocks.slice(0, firstChainIndex) : [];
  const chainBlocks = firstChainIndex >= 0 ? blocks.slice(firstChainIndex, lastChainIndex + 1) : [];
  const responseBlocks = lastChainIndex >= 0 ? blocks.slice(lastChainIndex + 1) : blocks;

  const toolCalls = chainBlocks
    .filter((b): b is { type: 'tool_call'; toolCall: ToolCall } => b.type === 'tool_call')
    .map(b => b.toolCall);
  const terminalBlocks = chainBlocks.filter(
    (b): b is ContentBlock & { type: 'terminal_command' } => b.type === 'terminal_command',
  );
  const youtubeApprovalBlocks = chainBlocks.filter(
    (b): b is ContentBlock & { type: 'youtube_transcription_approval' } =>
      b.type === 'youtube_transcription_approval',
  );
  const hasThinkingBlocks = chainBlocks.some((b) => b.type === 'thinking');

  const isAnyRunning = toolCalls.some(tc => tc.status === 'calling' || tc.status === 'progress');
  const isTerminalRunning = terminalBlocks.some(
    (block) => block.terminal.status === 'pending_approval' || block.terminal.status === 'running',
  );
  const isYouTubeApprovalPending = youtubeApprovalBlocks.some(
    (block) => block.approval.status === 'pending',
  );
  const isChainActive = isThinking || isAnyRunning || isTerminalRunning || isYouTubeApprovalPending;
  const allDone = toolCalls.length > 0 && !isAnyRunning;
  const isThinkingOnlyChain = hasThinkingBlocks
    && toolCalls.length === 0
    && terminalBlocks.length === 0
    && youtubeApprovalBlocks.length === 0;
  const [internalExpanded, setInternalExpanded] = useState(isChainActive || isThinkingOnlyChain);

  // Auto-expand while tools are running
  useEffect(() => {
    if (isChainActive || isThinkingOnlyChain) {
      setInternalExpanded(true);
    }
  }, [isChainActive, isThinkingOnlyChain]);

  const expanded = controlledExpanded ?? internalExpanded;
  const handleToggleExpanded = onToggleExpanded ?? (() => setInternalExpanded((prev) => !prev));

  // Extract text blocks from chainBlocks - these are actual model output, not thinking
  // They should be rendered as normal response text, not in the timeline
  const intermediateTextBlocks = chainBlocks.filter(
    (b): b is { type: 'text'; content: string } => b.type === 'text' && !!b.content.trim(),
  );

  // Build the flat list of timeline items (only thinking, tools, terminals, youtube_approval)
  // Text blocks are NOT included here - they are actual model output, not internal reasoning
  const timelineItems: Array<
    | { kind: 'thinking_tokens'; text: string }
    | { kind: 'tool'; toolCall: ToolCall }
    | { kind: 'terminal'; terminal: ContentBlock & { type: 'terminal_command' } }
    | {
      kind: 'youtube_approval';
      approval: ContentBlock & { type: 'youtube_transcription_approval' };
    }
    | { kind: 'done' }
  > = [];

  for (const block of chainBlocks) {
    if (block.type === 'thinking' && block.content.trim()) {
      // Model's internal reasoning tokens — collapsible with markdown rendering
      timelineItems.push({ kind: 'thinking_tokens', text: block.content });
    } else if (block.type === 'tool_call') {
      timelineItems.push({ kind: 'tool', toolCall: block.toolCall });
    } else if (block.type === 'terminal_command') {
      timelineItems.push({ kind: 'terminal', terminal: block as ContentBlock & { type: 'terminal_command' } });
    } else if (block.type === 'youtube_transcription_approval') {
      timelineItems.push({
        kind: 'youtube_approval',
        approval: block as ContentBlock & { type: 'youtube_transcription_approval' },
      });
    }
    // NOTE: text blocks are deliberately NOT added to timeline - they render separately
  }
  if (allDone) {
    timelineItems.push({ kind: 'done' });
  }

  const summary = (() => {
    if (toolCalls.length > 0) {
      return getChainSummary(toolCalls);
    }

    if (terminalBlocks.length > 0) {
      const noun = terminalBlocks.length === 1 ? 'terminal command' : 'terminal commands';
      return isChainActive ? `Running ${noun}` : `Ran ${terminalBlocks.length === 1 ? 'a' : terminalBlocks.length} ${noun}`;
    }

    if (youtubeApprovalBlocks.length > 0) {
      return isYouTubeApprovalPending
        ? 'Waiting for YouTube transcription approval'
        : 'Handled YouTube transcription approval';
    }

    if (hasThinkingBlocks) {
      return isThinking ? 'Thinking...' : 'Thought process';
    }

    return 'Processing...';
  })();
  const headerIcon = isChainActive ? <SpinnerIcon /> : (isThinkingOnlyChain ? <HourglassIcon /> : <CheckIcon />);

  return (
    <>
      {/* Pre-chain text (response text that appeared BEFORE any tool calls/thinking) */}
      {preChainBlocks.map((block, idx) => {
        if (block.type === 'text' && block.content.trim()) {
          return (
            <StreamingTextBlock
              key={`pre-${idx}`}
              content={block.content}
              isStreaming={false}
            />
          );
        }
        return null;
      })}

      {/* Chain section */}
      {chainBlocks.length > 0 && (
        <div className="tool-chain">
          <div className="tool-chain-header" onClick={handleToggleExpanded}>
            <div className="tool-chain-header-icon">
              {headerIcon}
            </div>
            <span className={`tool-chain-summary ${isChainActive ? 'running' : ''}`} title={summary}>{summary}</span>
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

                if (item.kind === 'youtube_approval') {
                  return (
                    <div key={idx} className="chain-item chain-item-terminal">
                      <div className="chain-item-marker">
                        <div className="chain-item-dot">
                          <WrenchIcon />
                        </div>
                        {!isLast && <div className="chain-item-line" />}
                      </div>
                      <div className="chain-item-body">
                        <InlineYouTubeApprovalBlock
                          approval={item.approval.approval}
                          onRespond={onYouTubeApprovalResponse}
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

      {/* Intermediate text (text that appeared BETWEEN tool calls/thinking - still model output, not thinking) */}
      {intermediateTextBlocks.map((block, idx) => (
        <StreamingTextBlock
          key={`mid-${idx}`}
          content={block.content}
          isStreaming={false}
        />
      ))}

      {/* Response text (after all tool calls) */}
      {responseBlocks.map((block, idx) => {
        if (block.type === 'text' && block.content.trim()) {
          // Use streaming animation for live streaming text
          return (
            <StreamingTextBlock
              key={`resp-${idx}`}
              content={block.content}
              isStreaming={isStreaming}
            />
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
        if (block.type === 'youtube_transcription_approval') {
          return (
            <InlineYouTubeApprovalBlock
              key={`resp-${idx}`}
              approval={block.approval}
              onRespond={onYouTubeApprovalResponse}
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
  isThinking?: boolean;
  isStreaming?: boolean;
  expanded?: boolean;
  onToggleExpanded?: () => void;
  onTerminalApprove?: (requestId: string) => void;
  onTerminalDeny?: (requestId: string) => void;
  onTerminalApproveRemember?: (requestId: string) => void;
  onTerminalKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
  onYouTubeApprovalResponse?: (requestId: string, approved: boolean) => void;
}

export function InlineContentBlocks({
  blocks,
  isThinking,
  isStreaming = false,
  expanded,
  onToggleExpanded,
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
  onYouTubeApprovalResponse,
}: InlineContentBlocksProps) {
  // Check if we have any "chain" blocks that need special rendering
  const hasChainBlocks = blocks.some(
    (block) =>
      block.type === 'thinking'
      || block.type === 'tool_call'
      || block.type === 'terminal_command'
      || block.type === 'youtube_transcription_approval',
  );

  // If we have chain blocks, use the interleaved timeline renderer
  if (hasChainBlocks) {
    return (
      <InterleavedContentBlocks
        blocks={blocks}
        isThinking={isThinking}
        isStreaming={isStreaming}
        expanded={expanded}
        onToggleExpanded={onToggleExpanded}
        onTerminalApprove={onTerminalApprove}
        onTerminalDeny={onTerminalDeny}
        onTerminalApproveRemember={onTerminalApproveRemember}
        onTerminalKill={onTerminalKill}
        onTerminalResize={onTerminalResize}
        onYouTubeApprovalResponse={onYouTubeApprovalResponse}
      />
    );
  }

  // No chain blocks — render text and terminals normally
  return (
    <>
      {blocks.map((block, idx) => {
        if (block.type === 'text' && block.content.trim()) {
          return (
            <StreamingTextBlock
              key={idx}
              content={block.content}
              isStreaming={isStreaming}
            />
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
        if (block.type === 'youtube_transcription_approval') {
          return (
            <InlineYouTubeApprovalBlock
              key={idx}
              approval={block.approval}
              onRespond={onYouTubeApprovalResponse}
            />
          );
        }
        return null;
      })}
    </>
  );
}

// ─── Interleaved Content Blocks (renders blocks in true sequence) ─────────────

// Helper to check if a block is a "chain" block (thinking/tool_call/terminal/youtube_approval)
function isChainBlock(block: ContentBlock): boolean {
  return (
    block.type === 'thinking'
    || block.type === 'tool_call'
    || block.type === 'terminal_command'
    || block.type === 'youtube_transcription_approval'
  );
}

// Group consecutive chain blocks together, with text blocks as separators
type BlockGroup =
  | { kind: 'text'; block: ContentBlock & { type: 'text' } }
  | { kind: 'chain'; blocks: ContentBlock[] };

function groupConsecutiveBlocks(blocks: ContentBlock[]): BlockGroup[] {
  const groups: BlockGroup[] = [];
  let currentChainGroup: ContentBlock[] = [];

  for (const block of blocks) {
    if (isChainBlock(block)) {
      // Add to current chain group
      currentChainGroup.push(block);
    } else if (block.type === 'text' && block.content.trim()) {
      // Text block - flush current chain group first
      if (currentChainGroup.length > 0) {
        groups.push({ kind: 'chain', blocks: currentChainGroup });
        currentChainGroup = [];
      }
      groups.push({ kind: 'text', block: block as ContentBlock & { type: 'text' } });
    }
    // Skip empty text blocks
  }

  // Flush remaining chain group
  if (currentChainGroup.length > 0) {
    groups.push({ kind: 'chain', blocks: currentChainGroup });
  }

  return groups;
}

function InterleavedContentBlocks({
  blocks,
  isThinking,
  isStreaming = false,
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
  onYouTubeApprovalResponse,
}: InlineContentBlocksProps) {
  // Group consecutive chain blocks together
  const groups = groupConsecutiveBlocks(blocks);

  return (
    <>
      {groups.map((group, groupIdx) => {
        if (group.kind === 'text') {
          return (
            <StreamingTextBlock
              key={`text-${groupIdx}`}
              content={group.block.content}
              isStreaming={isStreaming}
            />
          );
        }

        // Chain group - render as collapsible section
        return (
          <CollapsibleChainGroup
            key={`chain-${groupIdx}`}
            blocks={group.blocks}
            isThinking={isThinking}
            isStreaming={isStreaming}
            onTerminalApprove={onTerminalApprove}
            onTerminalDeny={onTerminalDeny}
            onTerminalApproveRemember={onTerminalApproveRemember}
            onTerminalKill={onTerminalKill}
            onTerminalResize={onTerminalResize}
            onYouTubeApprovalResponse={onYouTubeApprovalResponse}
          />
        );
      })}
    </>
  );
}

// ─── Collapsible Chain Group (groups consecutive thinking/tools under one header) ─

interface CollapsibleChainGroupProps {
  blocks: ContentBlock[];
  isThinking?: boolean;
  isStreaming?: boolean;
  onTerminalApprove?: (requestId: string) => void;
  onTerminalDeny?: (requestId: string) => void;
  onTerminalApproveRemember?: (requestId: string) => void;
  onTerminalKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
  onYouTubeApprovalResponse?: (requestId: string, approved: boolean) => void;
}

function CollapsibleChainGroup({
  blocks,
  isThinking,
  // isStreaming is accepted but not used currently - kept for API consistency
  onTerminalApprove,
  onTerminalDeny,
  onTerminalApproveRemember,
  onTerminalKill,
  onTerminalResize,
  onYouTubeApprovalResponse,
}: CollapsibleChainGroupProps) {
  const toolCalls = blocks
    .filter((b): b is { type: 'tool_call'; toolCall: ToolCall } => b.type === 'tool_call')
    .map((b) => b.toolCall);
  const terminalBlocks = blocks.filter(
    (b): b is ContentBlock & { type: 'terminal_command' } => b.type === 'terminal_command',
  );
  const youtubeApprovalBlocks = blocks.filter(
    (b): b is ContentBlock & { type: 'youtube_transcription_approval' } =>
      b.type === 'youtube_transcription_approval',
  );
  const hasThinkingBlocks = blocks.some((b) => b.type === 'thinking');

  const isAnyRunning = toolCalls.some((tc) => tc.status === 'calling' || tc.status === 'progress');
  const isTerminalRunning = terminalBlocks.some(
    (block) => block.terminal.status === 'pending_approval' || block.terminal.status === 'running',
  );
  const isYouTubeApprovalPending = youtubeApprovalBlocks.some(
    (block) => block.approval.status === 'pending',
  );
  const isChainActive = isThinking || isAnyRunning || isTerminalRunning || isYouTubeApprovalPending;
  const allToolsDone = toolCalls.length > 0 && !isAnyRunning;
  const isThinkingOnlyChain = hasThinkingBlocks
    && toolCalls.length === 0
    && terminalBlocks.length === 0
    && youtubeApprovalBlocks.length === 0;

  const [expanded, setExpanded] = useState(isChainActive || isThinkingOnlyChain);

  // Auto-expand while active
  useEffect(() => {
    if (isChainActive || isThinkingOnlyChain) {
      setExpanded(true);
    }
  }, [isChainActive, isThinkingOnlyChain]);

  // Generate summary text
  const summary = (() => {
    if (toolCalls.length > 0) {
      return getChainSummary(toolCalls);
    }

    if (terminalBlocks.length > 0) {
      const noun = terminalBlocks.length === 1 ? 'terminal command' : 'terminal commands';
      return isChainActive
        ? `Running ${noun}`
        : `Ran ${terminalBlocks.length === 1 ? 'a' : terminalBlocks.length} ${noun}`;
    }

    if (youtubeApprovalBlocks.length > 0) {
      return isYouTubeApprovalPending
        ? 'Waiting for YouTube transcription approval'
        : 'Handled YouTube transcription approval';
    }

    if (hasThinkingBlocks) {
      return isThinking ? 'Thinking...' : 'Thought process';
    }

    return 'Processing...';
  })();

  const headerIcon = isChainActive
    ? <SpinnerIcon />
    : (isThinkingOnlyChain ? <HourglassIcon /> : <CheckIcon />);

  return (
    <div className="tool-chain">
      <div className="tool-chain-header" onClick={() => setExpanded((prev) => !prev)}>
        <div className="tool-chain-header-icon">{headerIcon}</div>
        <span className={`tool-chain-summary ${isChainActive ? 'running' : ''}`} title={summary}>{summary}</span>
        <ChevronIcon expanded={expanded} />
      </div>

      {expanded && (
        <div className="tool-chain-timeline">
          {blocks.map((block, idx) => {
            const isLast = idx === blocks.length - 1 && allToolsDone;

            // Thinking block
            if (block.type === 'thinking' && block.content.trim()) {
              // For thinking-only chains, render content directly without marker/dot
              // since the outer header already has the hourglass icon
              if (isThinkingOnlyChain) {
                return (
                  <div key={idx} className="chain-item chain-item-thinking-only">
                    <div className="chain-item-body">
                      <div className="chain-thought-content">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{ code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>> }}
                        >
                          {block.content}
                        </ReactMarkdown>
                      </div>
                    </div>
                  </div>
                );
              }

              // Mixed chain (thinking + tools) - use collapsible wrapper with marker
              return (
                <div key={idx} className="chain-item">
                  <div className="chain-item-marker">
                    <div className="chain-item-dot">
                      {isThinking && idx === blocks.length - 1 ? <SpinnerIcon /> : <HourglassIcon />}
                    </div>
                    {!isLast && <div className="chain-item-line" />}
                  </div>
                  <ChainThinkingItem text={block.content} />
                </div>
              );
            }

            // Tool call block
            if (block.type === 'tool_call') {
              return (
                <ToolCallChainItem
                  key={idx}
                  toolCall={block.toolCall}
                  isLast={isLast}
                />
              );
            }

            // Terminal block
            if (block.type === 'terminal_command') {
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
                      terminal={block.terminal}
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

            // YouTube approval block
            if (block.type === 'youtube_transcription_approval') {
              return (
                <div key={idx} className="chain-item chain-item-terminal">
                  <div className="chain-item-marker">
                    <div className="chain-item-dot">
                      <WrenchIcon />
                    </div>
                    {!isLast && <div className="chain-item-line" />}
                  </div>
                  <div className="chain-item-body">
                    <InlineYouTubeApprovalBlock
                      approval={block.approval}
                      onRespond={onYouTubeApprovalResponse}
                    />
                  </div>
                </div>
              );
            }

            return null;
          })}

          {/* Done indicator */}
          {allToolsDone && (
            <div className="chain-item">
              <div className="chain-item-marker">
                <div className="chain-item-dot">
                  <CheckIcon />
                </div>
              </div>
              <div className="chain-item-body chain-done-text">Done</div>
            </div>
          )}
        </div>
      )}
    </div>
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
