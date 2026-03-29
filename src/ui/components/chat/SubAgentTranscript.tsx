import { useState, useMemo } from 'react';
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CodeBlock } from './CodeBlock';

// ─── Types ────────────────────────────────────────────────────────────────────

interface TranscriptTextStep {
  type: 'instruction' | 'text' | 'thinking';
  content: string;
}

interface TranscriptToolStep {
  type: 'tool_call';
  name: string;
  args: Record<string, unknown>;
  status: 'calling' | 'complete';
  result?: string;
}

type TranscriptStep = TranscriptTextStep | TranscriptToolStep;

// ─── SVG Icons (small versions for nested view) ──────────────────────────────

function MiniSpinnerIcon() {
  return (
    <svg className="sa-transcript-icon sa-transcript-icon-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  );
}

function MiniCheckIcon() {
  return (
    <svg className="sa-transcript-icon sa-transcript-icon-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function MiniChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg className={`sa-transcript-chevron ${expanded ? 'expanded' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

// ─── Tool Step Card ──────────────────────────────────────────────────────────

const ToolStepCard = React.memo(function ToolStepCard({ step }: { step: TranscriptToolStep }) {
  const [expanded, setExpanded] = useState(false);
  const isCalling = step.status === 'calling';

  const argsPreview = useMemo(() => {
    try {
      const str = JSON.stringify(step.args, null, 2);
      return str.length > 500 ? str.slice(0, 500) + '...' : str;
    } catch {
      return '{}';
    }
  }, [step.args]);

  const resultDisplay = useMemo(() => {
    if (!step.result) return null;
    return step.result.length > 2000 ? step.result.slice(0, 2000) + '\n...(truncated)' : step.result;
  }, [step.result]);

  return (
    <div className={`sa-tool-step ${isCalling ? 'sa-tool-step-calling' : 'sa-tool-step-complete'}`}>
      <div
        className="sa-tool-step-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="sa-tool-step-status">
          {isCalling ? <MiniSpinnerIcon /> : <MiniCheckIcon />}
        </span>
        <span className="sa-tool-step-name">{step.name}</span>
        <MiniChevronIcon expanded={expanded} />
      </div>
      {expanded && (
        <div className="sa-tool-step-body">
          <div className="sa-tool-step-section">
            <span className="sa-tool-step-label">Arguments</span>
            <pre className="sa-tool-step-pre">{argsPreview}</pre>
          </div>
          {resultDisplay && (
            <div className="sa-tool-step-section">
              <span className="sa-tool-step-label">Result</span>
              <pre className="sa-tool-step-pre">{resultDisplay}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

// ─── Main Component ──────────────────────────────────────────────────────────

interface SubAgentTranscriptProps {
  /** JSON-encoded array of transcript steps, or undefined */
  stepsJson: string | undefined;
  isRunning: boolean;
}

export function SubAgentTranscript({ stepsJson, isRunning }: SubAgentTranscriptProps) {
  const steps = useMemo<TranscriptStep[]>(() => {
    if (!stepsJson) return [];
    try {
      const parsed = JSON.parse(stepsJson);
      if (!Array.isArray(parsed)) return [];
      return parsed as TranscriptStep[];
    } catch (err) {
      // Fallback: if it's not valid JSON, it might be legacy plain text
      console.warn('SubAgentTranscript: failed to parse steps JSON', err);
      return [{ type: 'text', content: stepsJson }];
    }
  }, [stepsJson]);

  if (steps.length === 0) {
    return <span className="chain-subagent-waiting">Waiting for response...</span>;
  }

  return (
    <div className="sa-transcript">
      {steps.map((step, idx) => {
        const key = step.type === 'tool_call' ? `tc-${idx}-${step.name}` : `txt-${idx}`;
        if (step.type === 'instruction' || step.type === 'text' || step.type === 'thinking') {
          return (
            <div key={key} className="sa-transcript-text">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{ code: CodeBlock as React.ComponentType<React.ComponentPropsWithRef<'code'>> }}
              >
                {step.content}
              </ReactMarkdown>
            </div>
          );
        }
        if (step.type === 'tool_call') {
          return <ToolStepCard key={key} step={step} />;
        }
        return null;
      })}
      {isRunning && <span className="chain-subagent-streaming-indicator" />}
    </div>
  );
}
