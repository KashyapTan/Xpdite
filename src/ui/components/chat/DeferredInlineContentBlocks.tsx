import { InlineContentBlocks } from './ToolCallsDisplay';
import type { ContentBlock } from '../../types';

interface DeferredInlineContentBlocksProps {
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

export default function DeferredInlineContentBlocks(
  props: DeferredInlineContentBlocksProps,
) {
  return <InlineContentBlocks {...props} />;
}
