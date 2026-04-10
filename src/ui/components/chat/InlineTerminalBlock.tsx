/**
 * Inline Terminal Block Component.
 *
 * Renders a self-contained terminal command block embedded in the chat flow.
 * Each run_command invocation gets its own block showing:
 *   - Command header with status indicator
 *   - Approval buttons (when pending)
 *   - Scrollable output area:
 *       • xterm.js for PTY/interactive commands (full TUI rendering)
 *       • ansi-to-html for standard (non-PTY) commands
 *   - Completion footer (exit code, duration)
 *
 * Replaces the floating TerminalPanel overlay for a Copilot-like experience.
 */
import { useState, useRef, useEffect, useMemo } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import AnsiToHtml from 'ansi-to-html';
import type { TerminalCommandBlock } from '../../types';
import { getTerminalTheme } from '../../utils/theme';

const INIT_PTY_FLUSH_BATCH_SIZE = 250;
const MAX_RENDERABLE_OUTPUT_CHUNKS = 5000;

// Shared ANSI converter instance (for non-PTY commands only)
const ansiConverter = new AnsiToHtml({
  fg: 'var(--color-terminal-foreground)',
  bg: 'transparent',
  newline: true,
  escapeXML: true,
  colors: {
    0: 'var(--color-terminal-ansi-black)',
    1: 'var(--color-terminal-ansi-red)',
    2: 'var(--color-terminal-ansi-green)',
    3: 'var(--color-terminal-ansi-yellow)',
    4: 'var(--color-terminal-ansi-blue)',
    5: 'var(--color-terminal-ansi-magenta)',
    6: 'var(--color-terminal-ansi-cyan)',
    7: 'var(--color-terminal-ansi-white)',
    8: 'var(--color-terminal-ansi-bright-black)',
    9: 'var(--color-terminal-ansi-red)',
    10: 'var(--color-terminal-ansi-green)',
    11: 'var(--color-terminal-ansi-yellow)',
    12: 'var(--color-terminal-ansi-blue)',
    13: 'var(--color-terminal-ansi-magenta)',
    14: 'var(--color-terminal-ansi-cyan)',
    15: 'var(--color-terminal-ansi-bright-white)',
  },
});

interface InlineTerminalBlockProps {
  terminal: TerminalCommandBlock;
  onApprove?: (requestId: string) => void;
  onDeny?: (requestId: string) => void;
  onApproveRemember?: (requestId: string) => void;
  onKill?: (requestId: string) => void;
  onTerminalResize?: (cols: number, rows: number) => void;
}

export function InlineTerminalBlock({
  terminal,
  onApprove,
  onDeny,
  onApproveRemember,
  onKill,
  onTerminalResize,
}: InlineTerminalBlockProps) {
  const [isExpanded, setIsExpanded] = useState(() => !terminal.isPty);

  // Refs for non-PTY (ansi-to-html) output
  const outputEndRef = useRef<HTMLDivElement>(null);
  const outputContainerRef = useRef<HTMLDivElement>(null);

  // Refs for PTY (xterm.js) output
  const xtermContainerRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const writtenChunksRef = useRef<number>(0);
  const isInitialFlushPendingRef = useRef(false);
  const { requestId, command, shell, warning, cwd, status, output, outputChunks, isPty, exitCode, durationMs, timedOut } = terminal;
  const boundedOutputChunks = useMemo(
    () => (
      outputChunks.length > MAX_RENDERABLE_OUTPUT_CHUNKS
        ? outputChunks.slice(outputChunks.length - MAX_RENDERABLE_OUTPUT_CHUNKS)
        : outputChunks
    ),
    [outputChunks],
  );
  // Always-current ref so the RAF flush inside the init effect reads live chunks,
  // not the stale closure value captured when the effect ran.
  const outputChunksRef = useRef(boundedOutputChunks);
  // Stable refs for props/state used inside effects that shouldn't trigger re-init
  const onTerminalResizeRef = useRef(onTerminalResize);
  const statusRef = useRef(status);

  // Keep the ref in sync on every render
  outputChunksRef.current = boundedOutputChunks;
  onTerminalResizeRef.current = onTerminalResize;
  statusRef.current = status;

  // Ensure approval prompts are always expanded when they arrive.
  useEffect(() => {
    if (status === 'pending_approval') {
      setIsExpanded(true);
    }
  }, [status]);

  // ── xterm.js lifecycle for PTY commands ──────────────────────────

  // Initialize xterm when this is a PTY command and container is ready
  useEffect(() => {
    if (!isPty || !isExpanded || !xtermContainerRef.current || xtermRef.current) return;

    const terminalTheme = getTerminalTheme();
    let disposed = false;
    const term = new Terminal({
      theme: terminalTheme,
      fontSize: 12,
      fontFamily: "'Fira Code', 'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      cursorBlink: statusRef.current === 'running',
      cursorStyle: 'bar',
      disableStdin: true,
      scrollback: 10000,
      convertEol: false,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(xtermContainerRef.current);

    xtermRef.current = term;
    fitAddonRef.current = fitAddon;
    isInitialFlushPendingRef.current = true;
    const initialChunks = [...outputChunksRef.current];

    // Fit after browser paint and send size to backend
    requestAnimationFrame(() => {
      if (disposed) return;
      try {
        fitAddon.fit();
        // Send the actual xterm dimensions to the backend so PTY matches
        const resizeFn = onTerminalResizeRef.current;
        if (resizeFn && term.cols && term.rows) {
          resizeFn(term.cols, term.rows);
        }
      } catch { /* ignore */ }

      // Flush all chunks buffered before xterm was ready in batches.
      const flushInitialChunks = (startIdx: number) => {
        if (disposed) {
          isInitialFlushPendingRef.current = false;
          return;
        }

        const endIdx = Math.min(startIdx + INIT_PTY_FLUSH_BATCH_SIZE, initialChunks.length);
        for (let i = startIdx; i < endIdx; i += 1) {
          const chunk = initialChunks[i];
          if (chunk.raw) {
            term.write(chunk.text);
          } else {
            term.writeln(chunk.text);
          }
        }
        writtenChunksRef.current = endIdx;

        if (endIdx < initialChunks.length) {
          requestAnimationFrame(() => flushInitialChunks(endIdx));
          return;
        }

        isInitialFlushPendingRef.current = false;
        term.scrollToBottom();
      };

      if (initialChunks.length > 0) {
        flushInitialChunks(0);
      } else {
        isInitialFlushPendingRef.current = false;
      }
    });

    // ResizeObserver to keep xterm fitted
    const container = xtermContainerRef.current;
    const resizeObserver = new ResizeObserver(() => {
      if (container.offsetParent) {
        try {
          fitAddon.fit();
          // Sync new dimensions to backend PTY
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
      isInitialFlushPendingRef.current = false;
      resizeObserver.disconnect();
      term.dispose();
      xtermRef.current = null;
      fitAddonRef.current = null;
      writtenChunksRef.current = 0;
    };
  }, [isPty, isExpanded, requestId]); // Re-init when command identity changes

  // Write new chunks to xterm as they arrive (only runs once xterm is ready)
  useEffect(() => {
    if (!isPty || !xtermRef.current || !boundedOutputChunks || isInitialFlushPendingRef.current) return;

    const term = xtermRef.current;
    const startIdx = writtenChunksRef.current;
    if (startIdx >= boundedOutputChunks.length) return;

    for (let i = startIdx; i < boundedOutputChunks.length; i++) {
      const chunk = boundedOutputChunks[i];
      if (chunk.raw) {
        term.write(chunk.text);
      } else {
        term.writeln(chunk.text);
      }
    }
    writtenChunksRef.current = boundedOutputChunks.length;

    // Auto-scroll for non-TUI output
    if (status === 'running') {
      term.scrollToBottom();
    }
  }, [isPty, boundedOutputChunks, status]);

  // Update cursor blink based on status
  useEffect(() => {
    if (xtermRef.current) {
      xtermRef.current.options.cursorBlink = status === 'running';
    }
  }, [status]);

  // Re-fit xterm when expand/collapse changes
  useEffect(() => {
    if (isPty && isExpanded && fitAddonRef.current) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          try {
            fitAddonRef.current?.fit();
            xtermRef.current?.scrollToBottom();
          } catch { /* ignore */ }
        });
      });
    }
  }, [isPty, isExpanded]);

  // ── Non-PTY: auto-scroll for ansi-to-html output ────────────────

  useEffect(() => {
    if (isPty) return; // Skip for PTY mode
    const container = outputContainerRef.current;
    if (!container || !isExpanded) return;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    if (isNearBottom) {
      outputEndRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
    }
  }, [output, isExpanded, isPty]);

  // Convert ANSI output to HTML (non-PTY only)
  const outputHtml = useMemo(() => {
    if (isPty || !output) return '';
    return ansiConverter.toHtml(output);
  }, [output, isPty]);

  // Status indicator
  const statusIcon = (() => {
    switch (status) {
      case 'pending_approval':
        return (
          <svg className="terminal-inline-icon pending" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        );
      case 'denied':
        return (
          <svg className="terminal-inline-icon denied" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        );
      case 'running':
        return (
          <svg className="terminal-inline-icon running-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
        );
      case 'completed':
        return exitCode === 0 ? (
          <svg className="terminal-inline-icon success" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        ) : (
          <svg className="terminal-inline-icon error" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        );
    }
  })();

  // Footer text
  const footerText = (() => {
    if (status === 'denied') return 'Command denied';
    if (status === 'running') return 'Running...';
    if (status === 'pending_approval') return 'Awaiting approval';
    if (status === 'completed' && durationMs != null) {
      const dur = (durationMs / 1000).toFixed(1);
      const exitStr = exitCode === 0 ? 'exit 0' : `exit ${exitCode}`;
      const timeoutStr = timedOut ? ' (timed out)' : '';
      return `Completed in ${dur}s · ${exitStr}${timeoutStr}`;
    }
    return '';
  })();

  return (
    <div className={`terminal-inline-block status-${status}`}>
      {/* Header */}
      <div
        className="terminal-inline-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="terminal-inline-header-left">
          {statusIcon}
          <span className="terminal-inline-badge">{isPty ? 'PTY' : 'TERMINAL'}</span>
          <span className="terminal-inline-command" title={command}>
            {command}
          </span>
        </div>
        <div className="terminal-inline-header-right">
          {status === 'running' && onKill && (
            <button
              className="terminal-inline-kill"
              onClick={(e) => {
                e.stopPropagation();
                onKill(requestId);
              }}
            >
              Kill
            </button>
          )}
          <svg
            className={`terminal-inline-chevron ${isExpanded ? 'expanded' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </div>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="terminal-inline-body">
          {/* Approval prompt */}
          {status === 'pending_approval' && (
            <div className="terminal-inline-approval">
              <div className="terminal-inline-approval-info">
                <div className="terminal-inline-approval-label">Xpdite wants to run this command</div>
                {shell && <div className="terminal-inline-approval-cwd">shell: {shell}</div>}
                {cwd && <div className="terminal-inline-approval-cwd">in: {cwd}</div>}
                {warning && <div className="terminal-inline-warning">{warning}</div>}
              </div>
              <div className="terminal-inline-approval-actions">
                {onDeny && (
                  <button className="btn-deny" onClick={() => onDeny(requestId)}>
                    Deny
                  </button>
                )}
                {onApprove && (
                  <button className="btn-allow" onClick={() => onApprove(requestId)}>
                    Allow
                  </button>
                )}
                {onApproveRemember && (
                  <button className="btn-allow-remember" onClick={() => onApproveRemember(requestId)}>
                    Allow &amp; Remember
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Denied message */}
          {status === 'denied' && (
            <div className="terminal-inline-denied">
              Command was denied.
            </div>
          )}

          {/* PTY output area (xterm.js) */}
          {isPty && (status === 'running' || status === 'completed') && (
            <div className={`terminal-inline-xterm-wrapper${status === 'completed' ? ' pty-completed' : ''}`}>
              <div ref={xtermContainerRef} className="terminal-inline-xterm" />
            </div>
          )}

          {/* Standard output area (ansi-to-html) */}
          {!isPty && output && (
            <div className="terminal-inline-output" ref={outputContainerRef}>
              <pre
                className="terminal-inline-output-pre"
                dangerouslySetInnerHTML={{ __html: outputHtml }}
              />
              <div ref={outputEndRef} />
            </div>
          )}

          {/* Footer */}
          {footerText && status !== 'pending_approval' && (
            <div className={`terminal-inline-footer status-${status}`}>
              {footerText}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
