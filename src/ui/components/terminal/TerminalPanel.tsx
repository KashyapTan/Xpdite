/**
 * Terminal Panel Component.
 *
 * Floating overlay above the chat input area. Only visible when there's
 * an approval request, session request, or terminal output to show.
 * Uses xterm.js for terminal-like output rendering.
 *
 * Key design decisions:
 * - Buffers all writes that arrive before xterm is initialized, then
 *   flushes them once the terminal is ready (avoids race condition
 *   where requestAnimationFrame fires before useEffect initializes xterm).
 * - The parent should change the `key` prop on context-clear so internal
 *   state (hasOutput, buffer, xterm instance) resets cleanly.
 */
import { useRef, useEffect, useState, useCallback } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

import { ApprovalCard } from './ApprovalCard';
import { SessionBanner } from './SessionBanner';

import type {
  TerminalApprovalRequest,
  TerminalSessionRequest,
  TerminalRunningNotice,
} from '../../types';
import { getTerminalTheme } from '../../utils/theme';

const MAX_PENDING_WRITES = 5_000;
const PENDING_FLUSH_BATCH_SIZE = 250;

interface TerminalPanelProps {
  approvalRequest: TerminalApprovalRequest | null;
  sessionRequest: TerminalSessionRequest | null;
  sessionActive: boolean;
  runningNotice: TerminalRunningNotice | null;
  commandRunning: boolean;
  askLevel: string;
  onApprovalResponse: (requestId: string, approved: boolean, remember: boolean) => void;
  onSessionResponse: (approved: boolean) => void;
  onStopSession: () => void;
  onKillCommand: () => void;
  onAskLevelChange: (level: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
}

export function TerminalPanel({
  approvalRequest,
  sessionRequest,
  sessionActive,
  runningNotice,
  commandRunning,
  askLevel,
  onApprovalResponse,
  onSessionResponse,
  onStopSession,
  onKillCommand,
  onAskLevelChange,
  onTerminalResize,
}: TerminalPanelProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const pendingWrites = useRef<Array<{ type: 'line' | 'raw'; text: string }>>([]);
  const hasWarnedPendingOverflowRef = useRef(false);
  const [hasOutput, setHasOutput] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  // Stable ref for callback props used inside effects that shouldn't trigger re-init
  const onTerminalResizeRef = useRef(onTerminalResize);

  // Keep the ref in sync on every render
  onTerminalResizeRef.current = onTerminalResize;

  const enqueuePendingWrite = useCallback((entry: { type: 'line' | 'raw'; text: string }) => {
    pendingWrites.current.push(entry);
    if (pendingWrites.current.length > MAX_PENDING_WRITES) {
      const overflowCount = pendingWrites.current.length - MAX_PENDING_WRITES;
      pendingWrites.current.splice(0, overflowCount);
      if (!hasWarnedPendingOverflowRef.current) {
        console.warn(
          `[TerminalPanel] Pending write buffer exceeded ${MAX_PENDING_WRITES}; dropping oldest chunks.`,
        );
        hasWarnedPendingOverflowRef.current = true;
      }
    }
  }, []);

  // Determine if panel should be visible at all
  const hasInteraction = !!(approvalRequest || sessionRequest || sessionActive || runningNotice || commandRunning);
  const isVisible = hasInteraction || hasOutput;

  // ── xterm lifecycle ──────────────────────────────────────────────
  // Initialize xterm.js when output exists (container is in DOM).
  // Flush any buffered writes that arrived before initialization.
  useEffect(() => {
    if (!hasOutput || !terminalRef.current || xtermRef.current) return;

    const terminalTheme = getTerminalTheme();
    const term = new Terminal({
      theme: terminalTheme,
      fontSize: 13,
      fontFamily: "'Fira Code', 'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      cursorBlink: false,
      cursorStyle: 'bar',
      disableStdin: true,
      scrollback: 5000,
      convertEol: true,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);

    xtermRef.current = term;
    fitAddonRef.current = fitAddon;

    let disposed = false;

    // Fit after the browser has painted the container
    requestAnimationFrame(() => {
      if (disposed) return;
      try {
        fitAddon.fit();
        // Report terminal dimensions to backend for PTY sizing
        const resizeFn = onTerminalResizeRef.current;
        if (resizeFn && term.cols && term.rows) {
          resizeFn(term.cols, term.rows);
        }
      } catch { /* ignore */ }

      // Flush any writes that were buffered while xterm was not ready.
      // Chunk writes across frames so a huge backlog does not block rendering.
      const flushPendingWrites = () => {
        if (disposed) return;
        const batch = pendingWrites.current.splice(0, PENDING_FLUSH_BATCH_SIZE);
        if (batch.length === 0) {
          term.scrollToBottom();
          return;
        }

        for (const entry of batch) {
          if (entry.type === 'raw') {
            term.write(entry.text);
          } else {
            term.writeln(entry.text);
          }
        }
        if (pendingWrites.current.length > 0) {
          requestAnimationFrame(flushPendingWrites);
        } else {
          term.scrollToBottom();
        }
      };

      flushPendingWrites();
    });

    const container = terminalRef.current;
    const resizeObserver = new ResizeObserver(() => {
      // Only fit if visible
      if (container.offsetParent) {
          try {
            fitAddon.fit();
            term.scrollToBottom(); // Ensure we stay at bottom on resize if already there
            // Report updated dimensions after resize
            const resizeFn = onTerminalResizeRef.current;
            if (resizeFn && term.cols && term.rows) {
              resizeFn(term.cols, term.rows);
            }
          } catch { /* ignore */ }
      }
    });
    resizeObserver.observe(container);

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      term.dispose();
      xtermRef.current = null;
      fitAddonRef.current = null;
    };
  }, [hasOutput]); // Removed isExpanded dependency

  // Fit terminal when expanded state changes and scroll to bottom
  useEffect(() => {
    if (isExpanded && fitAddonRef.current && xtermRef.current) {
      // Use double RAF to ensure layout is settled after display: block
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          try {
            fitAddonRef.current?.fit();
            xtermRef.current?.scrollToBottom();
            // Report dimensions after fit
            const resizeFn = onTerminalResizeRef.current;
            if (resizeFn && xtermRef.current?.cols && xtermRef.current?.rows) {
              resizeFn(xtermRef.current.cols, xtermRef.current.rows);
            }
          } catch { /* ignore */ }
        });
      });
    }
  }, [isExpanded]);


  // Auto-expand when there's an approval request or session request
  useEffect(() => {
    if (approvalRequest || sessionRequest) {
      setIsExpanded(true);
    }
  }, [approvalRequest, sessionRequest]);

  // ── Write helpers ────────────────────────────────────────────────
  // Buffer writes when xterm isn't ready; write directly when it is.

  /** Write a line of text (adds newline) — for standard command output. */
  const writeLine = useCallback((text: string) => {
    if (xtermRef.current) {
      xtermRef.current.writeln(text);
      xtermRef.current.scrollToBottom();
    } else {
      enqueuePendingWrite({ type: 'line', text });
    }
  }, [enqueuePendingWrite]);

  /** Write raw data (no added newline) — for PTY/TUI ANSI output. */
  const writeRaw = useCallback((text: string) => {
    if (xtermRef.current) {
      xtermRef.current.write(text);
      // Don't auto-scroll raw writes as they might be cursor movements/TUI updates
    } else {
      enqueuePendingWrite({ type: 'raw', text });
    }
  }, [enqueuePendingWrite]);

  const writeOutput = useCallback((text: string) => {
    setHasOutput(true);
    setIsExpanded(true);
    writeLine(text);
  }, [writeLine]);

  /** Write raw PTY output — preserves ANSI cursor control for TUI rendering. */
  const writeOutputRaw = useCallback((text: string) => {
    setHasOutput(true);
    setIsExpanded(true);
    writeRaw(text);
  }, [writeRaw]);

  const writeCommand = useCallback((command: string) => {
    setHasOutput(true);
    setIsExpanded(true);
    writeLine(`\x1b[36m$ ${command}\x1b[0m`);
  }, [writeLine]);

  // Legacy debug bridge for local development only.
  // Terminal output now renders inline via InlineTerminalBlock.
  useEffect(() => {
    if (!import.meta.env.DEV) {
      return;
    }
    const w = window as unknown as Record<string, unknown>;
    w.__terminalWriteOutputDevOnly = writeOutput;
    w.__terminalWriteOutputRawDevOnly = writeOutputRaw;
    w.__terminalWriteCommandDevOnly = writeCommand;
    return () => {
      delete w.__terminalWriteOutputDevOnly;
      delete w.__terminalWriteOutputRawDevOnly;
      delete w.__terminalWriteCommandDevOnly;
    };
  }, [writeOutput, writeOutputRaw, writeCommand]);

  // Running notice text
  const runningText = runningNotice
    ? `Still running: ${runningNotice.command}  (${Math.round(runningNotice.elapsed_ms / 1000)}s)`
    : null;

  // Don't render anything if panel has nothing to show
  if (!isVisible) return null;

  return (
    <div className="terminal-panel-overlay">
      {/* Header bar */}
      <div className="terminal-header" onClick={() => setIsExpanded(!isExpanded)}>
        <div className="terminal-header-left">
          {/*<span className="terminal-icon">&#128421;</span>*/}
          <span className="terminal-title">Terminal</span>
          {runningText && <span className="terminal-running">{runningText}</span>}
        </div>
        <div className="terminal-header-right">
          {commandRunning && (
            <button
              className="btn-kill"
              onClick={(e) => {
                e.stopPropagation();
                onKillCommand();
              }}
            >
              Kill
            </button>
          )}
          <select
            className="terminal-ask-select"
            value={askLevel}
            onChange={(e) => {
              e.stopPropagation();
              onAskLevelChange(e.target.value);
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <option value="always">Always Ask</option>
            <option value="on-miss">Ask on Miss</option>
            <option value="off">Auto-Approve</option>
          </select>
          <span className="terminal-toggle">{isExpanded ? '\u25BC' : '\u25B2'}</span>
        </div>
      </div>

      {/* Session mode banner */}
      {sessionActive && (
        <SessionBanner onStop={onStopSession} />
      )}

      {/* Session request */}
      {sessionRequest && (
        <div className="terminal-session-request">
          <div className="session-request-header">Autonomous mode request</div>
          <div className="session-request-reason">{sessionRequest.reason}</div>
          <div className="session-request-actions">
            <button className="btn-deny" onClick={() => onSessionResponse(false)}>
              Deny
            </button>
            <button className="btn-allow" onClick={() => onSessionResponse(true)}>
              Allow
            </button>
          </div>
        </div>
      )}

      {/* Approval card */}
      {approvalRequest && (
        <ApprovalCard
          command={approvalRequest.command}
          cwd={approvalRequest.cwd}
          onAllow={() => onApprovalResponse(approvalRequest.request_id, true, false)}
          onDeny={() => onApprovalResponse(approvalRequest.request_id, false, false)}
          onAllowRemember={() => onApprovalResponse(approvalRequest.request_id, true, true)}
        />
      )}

      {/* Terminal output area — always rendered if output exists, but hidden via CSS if collapsed */}
      {hasOutput && (
        <div 
          className="terminal-body" 
          style={{ display: isExpanded ? 'block' : 'none' }}
        >
          <div ref={terminalRef} className="terminal-xterm" />
        </div>
      )}
    </div>
  );
}
