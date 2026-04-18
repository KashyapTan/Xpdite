import { describe, expect, test } from 'vitest';

import { ChatMessage, CodeBlock, ResponseArea, ThinkingSection, ToolCallsDisplay } from '../components/chat';
import { ModeSelector, QueryInput, ScreenshotChips, TokenUsagePopup } from '../components/input';
import { useChatState, useScreenshots, useTabKeyboardShortcuts, useTokenUsage } from '../hooks';
import { api as apiFromIndex } from '../services';
import { copyToClipboard as copyFromIndex } from '../utils';

import { ChatMessage as DirectChatMessage } from '../components/chat/ChatMessage';
import { CodeBlock as DirectCodeBlock } from '../components/chat/CodeBlock';
import { ResponseArea as DirectResponseArea } from '../components/chat/ResponseArea';
import { ThinkingSection as DirectThinkingSection } from '../components/chat/ThinkingSection';
import { ToolCallsDisplay as DirectToolCallsDisplay } from '../components/chat/ToolCallsDisplay';
import { ModeSelector as DirectModeSelector } from '../components/input/ModeSelector';
import { QueryInput as DirectQueryInput } from '../components/input/QueryInput';
import { ScreenshotChips as DirectScreenshotChips } from '../components/input/ScreenshotChips';
import { TokenUsagePopup as DirectTokenUsagePopup } from '../components/input/TokenUsagePopup';
import { useChatState as DirectUseChatState } from '../hooks/useChatState';
import { useScreenshots as DirectUseScreenshots } from '../hooks/useScreenshots';
import { useTabKeyboardShortcuts as DirectUseTabKeyboardShortcuts } from '../hooks/useTabKeyboardShortcuts';
import { useTokenUsage as DirectUseTokenUsage } from '../hooks/useTokenUsage';
import { api as directApi } from '../services/api';
import { copyToClipboard as directCopy } from '../utils/clipboard';

describe('barrel exports', () => {
  test('re-export chat components, input components, hooks, services, and utils from their index modules', () => {
    expect(ChatMessage).toBe(DirectChatMessage);
    expect(ThinkingSection).toBe(DirectThinkingSection);
    expect(ToolCallsDisplay).toBe(DirectToolCallsDisplay);
    expect(CodeBlock).toBe(DirectCodeBlock);
    expect(ResponseArea).toBe(DirectResponseArea);

    expect(QueryInput).toBe(DirectQueryInput);
    expect(ModeSelector).toBe(DirectModeSelector);
    expect(TokenUsagePopup).toBe(DirectTokenUsagePopup);
    expect(ScreenshotChips).toBe(DirectScreenshotChips);

    expect(useChatState).toBe(DirectUseChatState);
    expect(useScreenshots).toBe(DirectUseScreenshots);
    expect(useTabKeyboardShortcuts).toBe(DirectUseTabKeyboardShortcuts);
    expect(useTokenUsage).toBe(DirectUseTokenUsage);

    expect(apiFromIndex).toBe(directApi);
    expect(copyFromIndex).toBe(directCopy);
  });
});
