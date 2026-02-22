/**
 * Inline Terminal Block Component.
 *
 * Renders a self-contained terminal command block embedded in the chat flow.
 * Each run_command invocation gets its own block showing:
 *   - Command header with status indicator
 *   - Approval buttons (when pending)
 *   - Scrollable output area with ANSI color support
 *   - Completion footer (exit code, duration)
 *
 * Replaces the floating TerminalPanel overlay for a Copilot-like experience.
 */
import { useState, useMemo, useRef, useEffect } from 'react';
import AnsiToHtml from 'ansi-to-html';
import type { TerminalCommandBlock } from '../../types';

// Shared ANSI converter instance
const ansiConverter = new AnsiToHtml({
  fg: '#d4d4d4',
  bg: 'transparent',
  newline: true,
  escapeXML: true,
  colors: {
    0: '#1e1e1e',   // black
    1: '#f44747',   // red
    2: '#6a9955',   // green
    3: '#e0a040',   // yellow
    4: '#569cd6',   // blue
    5: '#c586c0',   // magenta
    6: '#4ec9b0',   // cyan
    7: '#d4d4d4',   // white
    8: '#808080',   // bright black
    9: '#f44747',   // bright red
    10: '#6a9955',  // bright green
    11: '#e0a040',  // bright yellow
    12: '#569cd6',  // bright blue
    13: '#c586c0',  // bright magenta
    14: '#4ec9b0',  // bright cyan
    15: '#ffffff',  // bright white
  },
});

interface InlineTerminalBlockProps {
  terminal: TerminalCommandBlock;
  onApprove?: (requestId: string) => void;
  onDeny?: (requestId: string) => void;
  onApproveRemember?: (requestId: string) => void;
  onKill?: (requestId: string) => void;
}

export function InlineTerminalBlock({
  terminal,
  onApprove,
  onDeny,
  onApproveRemember,
  onKill,
}: InlineTerminalBlockProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const outputEndRef = useRef<HTMLDivElement>(null);
  const outputContainerRef = useRef<HTMLDivElement>(null);

  const { requestId, command, cwd, status, output, exitCode, durationMs, timedOut } = terminal;

  // Auto-scroll output to bottom when new content arrives (only if near bottom)
  useEffect(() => {
    const container = outputContainerRef.current;
    if (!container || !isExpanded) return;
    
    // Auto-scroll if user is near the bottom (within 60px)
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    if (isNearBottom) {
      outputEndRef.current?.scrollIntoView({ behavior: 'instant', block: 'end' });
    }
  }, [output, isExpanded]);

  // Convert ANSI output to HTML
  const outputHtml = useMemo(() => {
    if (!output) return '';
    return ansiConverter.toHtml(output);
  }, [output]);

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
          <span className="terminal-inline-badge">TERMINAL</span>
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
                {cwd && <div className="terminal-inline-approval-cwd">in: {cwd}</div>}
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

          {/* Output area */}
          {output && (
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
