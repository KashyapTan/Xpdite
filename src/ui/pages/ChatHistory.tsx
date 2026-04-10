import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import { XIcon } from '../components/icons/AppIcons';
import { useTabs } from '../contexts/TabContext';
import { useWebSocket } from '../contexts/WebSocketContext';
import '../CSS/pages/ChatHistory.css';

interface Conversation {
  id: string;
  title: string;
  date: number; // Unix timestamp
}

const CONVERSATIONS_PER_PAGE = 50;

const ChatHistory: React.FC = () => {
  const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();
  const navigate = useNavigate();
  const { send, subscribe, isConnected } = useWebSocket();
  const { createTab } = useTabs();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [hasMore, setHasMore] = useState<boolean>(true);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listContainerRef = useRef<HTMLDivElement>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement>(null);
  // Refs for synchronous access in IntersectionObserver callback to avoid race conditions
  const loadingMoreRef = useRef<boolean>(false);
  const hasMoreRef = useRef<boolean>(true);
  const conversationsLengthRef = useRef<number>(0);

  // Subscribe to WebSocket messages and fetch conversations on connect
  useEffect(() => {
    const unsubscribe = subscribe((data) => {
      switch (data.type) {
        case '__ws_connected': {
          // Request conversations list on connect
          setConversations([]);
          conversationsLengthRef.current = 0;
          setHasMore(true);
          hasMoreRef.current = true;
          send({ type: 'get_conversations', limit: CONVERSATIONS_PER_PAGE, offset: 0 });
          break;
        }
        case 'conversations_list': {
          const convos = data.content as Conversation[];
          const responseOffset = data.offset as number | undefined;
          const responseHasMore = data.has_more as boolean | undefined;

          // If this is a response to a search or first page load (offset 0)
          if (responseOffset === undefined || responseOffset === 0) {
            setConversations(convos);
            conversationsLengthRef.current = convos.length;
          } else {
            // Append new conversations for pagination
            setConversations(prev => {
              const newConversations = [...prev, ...convos];
              conversationsLengthRef.current = newConversations.length;
              return newConversations;
            });
          }

          const newHasMore = responseHasMore ?? false;
          setHasMore(newHasMore);
          hasMoreRef.current = newHasMore;
          setLoading(false);
          setLoadingMore(false);
          loadingMoreRef.current = false;
          break;
        }
        case 'conversation_deleted': {
          const deleteData = data.content as { conversation_id: string };
          setConversations(prev => {
            const newConversations = prev.filter(c => c.id !== deleteData.conversation_id);
            conversationsLengthRef.current = newConversations.length;
            return newConversations;
          });
          break;
        }
        case 'error': {
          console.error('ChatHistory received error from backend:', data.content);
          setLoading(false);
          setLoadingMore(false);
          loadingMoreRef.current = false;
          break;
        }
      }
    });

    // If already connected when this component mounts, fetch immediately
    if (isConnected) {
      setConversations([]);
      conversationsLengthRef.current = 0;
      setHasMore(true);
      hasMoreRef.current = true;
      send({ type: 'get_conversations', limit: CONVERSATIONS_PER_PAGE, offset: 0 });
    }

    return unsubscribe;
  }, [send, subscribe, isConnected]);

  // Intersection observer for infinite scroll
  // Uses refs for synchronous access to avoid race conditions in the observer callback
  useEffect(() => {
    if (!loadMoreTriggerRef.current || searchQuery.trim()) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        // Use refs for synchronous, race-free checks
        if (entry.isIntersecting && hasMoreRef.current && !loadingMoreRef.current && !loading) {
          const newOffset = conversationsLengthRef.current;
          // Set ref synchronously before async state update to prevent duplicate requests
          loadingMoreRef.current = true;
          setLoadingMore(true);
          send({ type: 'get_conversations', limit: CONVERSATIONS_PER_PAGE, offset: newOffset });
        }
      },
      {
        root: listContainerRef.current,
        rootMargin: '100px',
        threshold: 0.1,
      }
    );

    observer.observe(loadMoreTriggerRef.current);

    return () => {
      observer.disconnect();
    };
  }, [loading, send, searchQuery]);

  // Debounced search
  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value);

    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }

    searchTimeoutRef.current = setTimeout(() => {
      if (value.trim()) {
        // Search resets to initial state
        setConversations([]);
        conversationsLengthRef.current = 0;
        setHasMore(false); // Search results don't support pagination
        hasMoreRef.current = false;
        send({ type: 'search_conversations', query: value.trim() });
      } else {
        // Clear search: reset and fetch first page
        setConversations([]);
        conversationsLengthRef.current = 0;
        setHasMore(true);
        hasMoreRef.current = true;
        send({ type: 'get_conversations', limit: CONVERSATIONS_PER_PAGE, offset: 0 });
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
                type="button"
                className="chat-history-delete-btn"
                onClick={(e) => handleDeleteConversation(e, convo.id)}
                title="Delete conversation"
                aria-label={`Delete ${convo.title}`}
              >
                <XIcon size={14} />
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
        <div className="chat-history-list-container" ref={listContainerRef}>
          {loading ? (
            <div className="chat-history-empty-state">Loading conversations...</div>
          ) : conversations.length === 0 ? (
            <div className="chat-history-empty-state">
              {searchQuery ? 'No conversations match your search.' : 'No conversations yet. Start chatting!'}
            </div>
          ) : (
            <>
              {renderConversations()}
              {/* Infinite scroll trigger element */}
              {hasMore && !searchQuery.trim() && (
                <div ref={loadMoreTriggerRef} className="chat-history-load-more-trigger">
                  {loadingMore && <div className="chat-history-loading-more">Loading more...</div>}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
};

export default ChatHistory;
