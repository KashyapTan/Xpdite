import { ChatMessage } from './ChatMessage';
import type { ChatMessage as ChatMessageType } from '../../types';

interface DeferredChatHistoryProps {
  chatHistory: ChatMessageType[];
  generatingModel: string;
  canSubmit: boolean;
  onRetryMessage: (message: ChatMessageType) => void;
  onEditMessage: (message: ChatMessageType, content: string) => void;
  onSetActiveResponse: (message: ChatMessageType, responseIndex: number) => void;
}

export default function DeferredChatHistory({
  chatHistory,
  generatingModel,
  canSubmit,
  onRetryMessage,
  onEditMessage,
  onSetActiveResponse,
}: DeferredChatHistoryProps) {
  return (
    <>
      {chatHistory.map((message, index) => (
        <ChatMessage
          key={message.messageId ?? `${message.role}-${index}`}
          message={message}
          selectedModel={generatingModel}
          actionsDisabled={!canSubmit}
          onRetryMessage={onRetryMessage}
          onEditMessage={onEditMessage}
          onSetActiveResponse={onSetActiveResponse}
        />
      ))}
    </>
  );
}
