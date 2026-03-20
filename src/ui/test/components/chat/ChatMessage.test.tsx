/**
 * Tests for the ChatMessage component.
 */
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatMessage } from '../../../components/chat/ChatMessage';
import type { ChatMessage as ChatMessageType } from '../../../types';

// Mock the clipboard utility
vi.mock('../../../utils/clipboard', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(undefined),
}));

// Mock the chatMessages utilities
vi.mock('../../../utils/chatMessages', () => ({
  buildRenderableContentBlocks: vi.fn((message) => {
    if (message.contentBlocks && message.contentBlocks.length > 0) {
      return message.contentBlocks;
    }
    return undefined;
  }),
  formatMessageTimestamp: vi.fn((timestamp) => {
    if (!timestamp) return '';
    return '10:30 AM';
  }),
  serializeMessageForCopy: vi.fn((message) => message.content),
}));

// Get access to the mocked functions
import { copyToClipboard } from '../../../utils/clipboard';

describe('ChatMessage', () => {
  const defaultProps = {
    selectedModel: 'gpt-4',
    actionsDisabled: false,
    onRetryMessage: vi.fn(),
    onEditMessage: vi.fn(),
    onSetActiveResponse: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('User Message Rendering', () => {
    test('renders user message content', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Hello, how are you?',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
    });

    test('renders user message with correct CSS class', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      const { container } = render(<ChatMessage message={message} {...defaultProps} />);

      expect(container.querySelector('.chat-user')).toBeInTheDocument();
      expect(container.querySelector('.query')).toBeInTheDocument();
    });

    test('renders slash commands with code formatting', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Start with /help command',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      const { container } = render(<ChatMessage message={message} {...defaultProps} />);

      const codeElement = container.querySelector('code.slash-command-history');
      expect(codeElement).toBeInTheDocument();
      expect(codeElement).toHaveTextContent('/help');
    });

    test('renders images attached to user message', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Check this image',
        messageId: 'user-1',
        timestamp: Date.now(),
        images: [
          { name: 'screenshot.png', thumbnail: 'base64data' },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getAllByText('screenshot.png').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Assistant Message Rendering', () => {
    test('renders assistant message content', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Hello! I can help you.',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        model: 'gpt-4',
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('Hello! I can help you.')).toBeInTheDocument();
    });

    test('renders assistant message with correct CSS class', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      const { container } = render(<ChatMessage message={message} {...defaultProps} />);

      expect(container.querySelector('.chat-assistant')).toBeInTheDocument();
      expect(container.querySelector('.response')).toBeInTheDocument();
    });

    test('renders assistant header with model name', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response text',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        model: 'claude-3',
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('Xpdite • claude-3')).toBeInTheDocument();
    });

    test('uses selectedModel when message model is not set', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response text',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} selectedModel="gpt-4" />);

      expect(screen.getByText('Xpdite • gpt-4')).toBeInTheDocument();
    });
  });

  describe('Timestamp Display', () => {
    test('renders formatted timestamp for user message', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('10:30 AM')).toBeInTheDocument();
    });

    test('renders formatted timestamp for assistant message', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('10:30 AM')).toBeInTheDocument();
    });
  });

  describe('Copy Button Functionality', () => {
    test('renders copy button for user message', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByTitle('Copy message')).toBeInTheDocument();
    });

    test('renders copy button for assistant message', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByTitle('Copy message')).toBeInTheDocument();
    });

    test('copies user message content to clipboard when copy button is clicked', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Copy this text',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const copyButton = screen.getByTitle('Copy message');
      await userEvent.click(copyButton);

      expect(copyToClipboard).toHaveBeenCalledWith('Copy this text');
    });

    test('copies assistant message content to clipboard when copy button is clicked', async () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Assistant response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const copyButton = screen.getByTitle('Copy message');
      await userEvent.click(copyButton);

      expect(copyToClipboard).toHaveBeenCalled();
    });
  });

  describe('Retry Button Functionality', () => {
    test('renders retry button for user message', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByTitle('Retry message')).toBeInTheDocument();
    });

    test('renders retry button for assistant message', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByTitle('Retry message')).toBeInTheDocument();
    });

    test('calls onRetryMessage when retry button is clicked', async () => {
      const onRetryMessage = vi.fn();
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          onRetryMessage={onRetryMessage}
        />
      );

      const retryButton = screen.getByTitle('Retry message');
      await userEvent.click(retryButton);

      expect(onRetryMessage).toHaveBeenCalledWith(message);
    });

    test('retry button is disabled when actionsDisabled is true', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          actionsDisabled={true}
        />
      );

      const retryButton = screen.getByTitle('Retry message');
      expect(retryButton).toBeDisabled();
    });

    test('retry button is disabled when message has no messageId', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const retryButton = screen.getByTitle('Retry message');
      expect(retryButton).toBeDisabled();
    });
  });

  describe('Edit Functionality (User Messages Only)', () => {
    test('renders edit button for user message', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByTitle('Edit message')).toBeInTheDocument();
    });

    test('does not render edit button for assistant message', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Test response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.queryByTitle('Edit message')).not.toBeInTheDocument();
    });

    test('enters edit mode when edit button is clicked', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      expect(screen.getByRole('textbox')).toBeInTheDocument();
      expect(screen.getByRole('textbox')).toHaveValue('Original message');
    });

    test('shows Save and Cancel buttons in edit mode', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      expect(screen.getByText('Save')).toBeInTheDocument();
      expect(screen.getByText('Cancel')).toBeInTheDocument();
    });

    test('cancels edit mode and restores content when Cancel is clicked', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Modify the content
      const textarea = screen.getByRole('textbox');
      await userEvent.clear(textarea);
      await userEvent.type(textarea, 'Modified message');

      // Click Cancel
      const cancelButton = screen.getByText('Cancel');
      await userEvent.click(cancelButton);

      // Should exit edit mode
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.getByText('Original message')).toBeInTheDocument();
    });

    test('calls onEditMessage when Save is clicked with changed content', async () => {
      const onEditMessage = vi.fn();
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          onEditMessage={onEditMessage}
        />
      );

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Modify the content
      const textarea = screen.getByRole('textbox');
      await userEvent.clear(textarea);
      await userEvent.type(textarea, 'Modified message');

      // Click Save
      const saveButton = screen.getByText('Save');
      await userEvent.click(saveButton);

      expect(onEditMessage).toHaveBeenCalledWith(message, 'Modified message');
    });

    test('Save button is disabled when content is unchanged', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Save button should be disabled (content unchanged)
      const saveButton = screen.getByText('Save');
      expect(saveButton).toBeDisabled();
    });

    test('Save button is disabled when content is empty', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Clear content
      const textarea = screen.getByRole('textbox');
      await userEvent.clear(textarea);

      // Save button should be disabled (empty content)
      const saveButton = screen.getByText('Save');
      expect(saveButton).toBeDisabled();
    });

    test('cancels edit mode when Escape key is pressed', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Press Escape
      const textarea = screen.getByRole('textbox');
      fireEvent.keyDown(textarea, { key: 'Escape' });

      // Should exit edit mode
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    });

    test('saves edit when Ctrl+Enter is pressed', async () => {
      const onEditMessage = vi.fn();
      const message: ChatMessageType = {
        role: 'user',
        content: 'Original message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          onEditMessage={onEditMessage}
        />
      );

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Modify content and press Ctrl+Enter
      const textarea = screen.getByRole('textbox');
      await userEvent.clear(textarea);
      await userEvent.type(textarea, 'New content');
      fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });

      expect(onEditMessage).toHaveBeenCalledWith(message, 'New content');
    });

    test('edit button is disabled when actionsDisabled is true', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          actionsDisabled={true}
        />
      );

      const editButton = screen.getByTitle('Edit message');
      expect(editButton).toBeDisabled();
    });
  });

  describe('Response Version Navigation', () => {
    test('renders navigation arrows when multiple response versions exist', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 1',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 0,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByTitle('Previous response')).toBeInTheDocument();
      expect(screen.getByTitle('Next response')).toBeInTheDocument();
    });

    test('does not render navigation when only one response version exists', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Only response',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        responseVersions: [
          { responseIndex: 0, content: 'Only response', timestamp: Date.now() },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.queryByTitle('Previous response')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Next response')).not.toBeInTheDocument();
    });

    test('displays current response index', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 1',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 0,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
          { responseIndex: 2, content: 'Response version 3', timestamp: Date.now() },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('1 / 3')).toBeInTheDocument();
    });

    test('calls onSetActiveResponse when next arrow is clicked', async () => {
      const onSetActiveResponse = vi.fn();
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 1',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 0,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
        ],
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          onSetActiveResponse={onSetActiveResponse}
        />
      );

      const nextButton = screen.getByTitle('Next response');
      await userEvent.click(nextButton);

      expect(onSetActiveResponse).toHaveBeenCalledWith(message, 1);
    });

    test('calls onSetActiveResponse when previous arrow is clicked', async () => {
      const onSetActiveResponse = vi.fn();
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 2',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 1,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
        ],
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          onSetActiveResponse={onSetActiveResponse}
        />
      );

      const prevButton = screen.getByTitle('Previous response');
      await userEvent.click(prevButton);

      expect(onSetActiveResponse).toHaveBeenCalledWith(message, 0);
    });

    test('previous arrow is disabled on first response', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 1',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 0,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const prevButton = screen.getByTitle('Previous response');
      expect(prevButton).toBeDisabled();
    });

    test('next arrow is disabled on last response', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 2',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 1,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      const nextButton = screen.getByTitle('Next response');
      expect(nextButton).toBeDisabled();
    });

    test('navigation arrows are disabled when actionsDisabled is true', () => {
      const message: ChatMessageType = {
        role: 'assistant',
        content: 'Response version 1',
        messageId: 'assistant-1',
        timestamp: Date.now(),
        activeResponseIndex: 0,
        responseVersions: [
          { responseIndex: 0, content: 'Response version 1', timestamp: Date.now() },
          { responseIndex: 1, content: 'Response version 2', timestamp: Date.now() },
          { responseIndex: 2, content: 'Response version 3', timestamp: Date.now() },
        ],
      };

      render(
        <ChatMessage
          message={message}
          {...defaultProps}
          actionsDisabled={true}
        />
      );

      const nextButton = screen.getByTitle('Next response');
      expect(nextButton).toBeDisabled();
    });
  });

  describe('Message Images', () => {
    test('renders multiple images', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Check these images',
        messageId: 'user-1',
        timestamp: Date.now(),
        images: [
          { name: 'image1.png', thumbnail: 'base64data1' },
          { name: 'image2.jpg', thumbnail: 'base64data2' },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getAllByText('image1.png').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('image2.jpg').length).toBeGreaterThanOrEqual(1);
    });

    test('renders placeholder for images without thumbnails', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Check this image',
        messageId: 'user-1',
        timestamp: Date.now(),
        images: [
          { name: 'image.png', thumbnail: '' },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getByText('[IMG]')).toBeInTheDocument();
    });

    test('uses default image name when name is empty', () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Check this image',
        messageId: 'user-1',
        timestamp: Date.now(),
        images: [
          { name: '', thumbnail: 'base64data' },
        ],
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      expect(screen.getAllByText('Image 1').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Footer Visibility', () => {
    test('hides footer buttons when in edit mode', async () => {
      const message: ChatMessageType = {
        role: 'user',
        content: 'Test message',
        messageId: 'user-1',
        timestamp: Date.now(),
      };

      render(<ChatMessage message={message} {...defaultProps} />);

      // Initially footer buttons are visible
      expect(screen.getByTitle('Copy message')).toBeInTheDocument();

      // Enter edit mode
      const editButton = screen.getByTitle('Edit message');
      await userEvent.click(editButton);

      // Footer buttons should be hidden
      expect(screen.queryByTitle('Copy message')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Edit message')).not.toBeInTheDocument();
      expect(screen.queryByTitle('Retry message')).not.toBeInTheDocument();
    });
  });
});
