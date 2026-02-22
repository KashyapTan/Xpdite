import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import '../CSS/ChatHistory.css';

interface Conversation {
  id: string;
  title: string;
  date: number; // Unix timestamp
}

const ChatHistory: React.FC = () => {
  const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const wsRef = useRef<WebSocket | null>(null);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Connect to WebSocket and fetch conversations
  useEffect(() => {
    let ws: WebSocket | null = null;

    const connect = () => {
      ws = new WebSocket('ws://localhost:8000/ws');
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('ChatHistory WS connected');
        // Request conversations list on connect
        ws?.send(JSON.stringify({ type: 'get_conversations', limit: 50, offset: 0 }));
      };

      ws.onmessage = (event) => {
        console.log('ChatHistory received message:', event.data);
        try {
          const data = JSON.parse(event.data);
          switch (data.type) {
            case 'conversations_list': {
              const convos = data.content as Conversation[];
              console.log('Parsed conversations:', convos);
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
        } catch (e) {
          console.error('ChatHistory WS parsing error:', e);
        }
      };

      ws.onclose = () => {
        // Reconnect after a brief delay
        setTimeout(connect, 2000);
      };
    };

    connect();

    return () => {
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, []);

  // Debounced search
  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value);

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        if (value.trim()) {
          wsRef.current.send(JSON.stringify({ type: 'search_conversations', query: value.trim() }));
        } else {
          wsRef.current.send(JSON.stringify({ type: 'get_conversations', limit: 50, offset: 0 }));
        }
      }
    }, 300);
  }, []);

  const handleConversationClick = (conversationId: string) => {
    // Navigate to the main chat page with the conversation ID in state
    navigate('/', { state: { conversationId } });
  };

  const handleDeleteConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation(); // Prevent triggering the click on the list item
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'delete_conversation', conversation_id: conversationId }));
    }
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
      <TitleBar onClearContext={() => { }} setMini={setMini} />
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
