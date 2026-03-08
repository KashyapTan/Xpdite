import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import { useTabs } from '../contexts/TabContext';
import { useWebSocket } from '../contexts/WebSocketContext';
import '../CSS/ChatHistory.css';

interface Conversation {
  id: string;
  title: string;
  date: number; // Unix timestamp
}

const ChatHistory: React.FC = () => {
  const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();
  const navigate = useNavigate();
  const { send, subscribe, isConnected } = useWebSocket();
  const { createTab } = useTabs();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Subscribe to WebSocket messages and fetch conversations on connect
  useEffect(() => {
    const unsubscribe = subscribe((data) => {
      switch (data.type) {
        case '__ws_connected': {
          // Request conversations list on connect
          send({ type: 'get_conversations', limit: 50, offset: 0 });
          break;
        }
        case 'conversations_list': {
          const convos = data.content as Conversation[];
          setConversations(convos);
          setLoading(false);
          break;
        }
        case 'conversation_deleted': {
          const deleteData = data.content;
          setConversations(prev => prev.filter(c => c.id !== deleteData.conversation_id));
          break;
        }
        case 'error': {
          console.error('ChatHistory received error from backend:', data.content);
          setLoading(false);
          break;
        }
      }
    });

    // If already connected when this component mounts, fetch immediately
    if (isConnected) {
      send({ type: 'get_conversations', limit: 50, offset: 0 });
    }

    return unsubscribe;
  }, [send, subscribe, isConnected]);

  // Debounced search
  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value);

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(() => {
      if (value.trim()) {
        send({ type: 'search_conversations', query: value.trim() });
      } else {
        send({ type: 'get_conversations', limit: 50, offset: 0 });
      }
    }, 300);
  }, [send]);

  const handleConversationClick = (conversationId: string) => {
    const tabId = createTab();
    if (!tabId) {
      return;
    }

    navigate('/', { state: { conversationId, tabId } });
  };

  const handleDeleteConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation(); // Prevent triggering the click on the list item
    send({ type: 'delete_conversation', conversation_id: conversationId });
  };

  const getRelativeDateGroup = (timestamp: number): string => {
    const date = new Date(timestamp * 1000);
    const now = new Date();

    // Normalize to midnight for accurate comparison
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    const convoDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    if (convoDate.getTime() === today.getTime()) {
      return 'Today';
    } else if (convoDate.getTime() === yesterday.getTime()) {
      return 'Yesterday';
    } else {
      return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
    }
  };

  const formatTime = (timestamp: number): string => {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  };

  const renderConversations = () => {
    let lastGroup = '';

    return conversations.map((convo) => {
      const currentGroup = getRelativeDateGroup(convo.date);
      const showHeader = currentGroup !== lastGroup;
      lastGroup = currentGroup;

      return (
        <React.Fragment key={convo.id}>
          {showHeader && (
            <div className="chat-history-date-separator">
              <span>{currentGroup}</span>
            </div>
          )}
          <div
            className="chat-history-list-item"
            onClick={() => handleConversationClick(convo.id)}
          >
            <div className="chat-history-list-item-description">{convo.title}</div>
            <div className="chat-history-list-item-date-section">

              <button
                className="chat-history-delete-btn"
                onClick={(e) => handleDeleteConversation(e, convo.id)}
                title="Delete conversation"
              >
                ×
              </button>
              <span className="chat-history-list-item-time">{formatTime(convo.date)}</span>
            </div>
          </div>
        </React.Fragment>
      );
    });
  };

  return (
    <>
      <TitleBar setMini={setMini} />
      <div className="chat-history-container">
        <div className="chat-history-search-box-container">
          <form className='chat-history-search-box-form' onSubmit={(e) => e.preventDefault()}>
            <input
              type="text"
              placeholder="Search chat history..."
              className="chat-history-search-box-input"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
            />
          </form>
        </div>
        <div className="chat-history-list-container">
          {loading ? (
            <div className="chat-history-empty-state">Loading conversations...</div>
          ) : conversations.length === 0 ? (
            <div className="chat-history-empty-state">
              {searchQuery ? 'No conversations match your search.' : 'No conversations yet. Start chatting!'}
            </div>
          ) : renderConversations()}
        </div>
      </div>
    </>
  );
};

export default ChatHistory;
