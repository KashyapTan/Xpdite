import React, { useState, useEffect, useCallback } from 'react';
import { useOutletContext, useNavigate } from 'react-router-dom';
import TitleBar from '../components/TitleBar';
import { XIcon } from '../components/icons/AppIcons';
import { useTabs } from '../contexts/TabContext';
import { useWebSocket } from '../contexts/WebSocketContext';
import { api } from '../services/api';
import '../CSS/pages/ScheduledJobsResults.css';

interface JobConversation {
  id: string;
  job_id: string;
  job_name: string | null;
  title: string;
  created_at: number;
  updated_at: number;
}

interface ScheduledJob {
  id: string;
  name: string;
  cron_expression: string;
  enabled: boolean;
}

const ScheduledJobsResults: React.FC = () => {
  const { setMini } = useOutletContext<{ setMini: (val: boolean) => void }>();
  const navigate = useNavigate();
  const { send, subscribe } = useWebSocket();
  const { createTab } = useTabs();
  const [conversations, setConversations] = useState<JobConversation[]>([]);
  const [jobs, setJobs] = useState<Record<string, ScheduledJob>>({});
  const [loading, setLoading] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [convosData, jobsData] = await Promise.all([
        api.getScheduledJobConversations(),
        api.getScheduledJobs(),
      ]);

      setConversations(convosData.conversations);

      // Build a map of job_id -> job for quick lookup
      const jobMap: Record<string, ScheduledJob> = {};
      for (const job of jobsData.jobs) {
        jobMap[job.id] = job;
      }
      setJobs(jobMap);
    } catch (error) {
      console.error('Failed to fetch scheduled job results:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Subscribe to WebSocket for real-time updates
  useEffect(() => {
    const unsubscribe = subscribe((data) => {
      if (data.type === 'conversation_deleted') {
        const deleteData = data.content as { conversation_id: string };
        setConversations((prev) => prev.filter((c) => c.id !== deleteData.conversation_id));
      } else if (data.type === 'notification_added') {
        // A new notification was added - check if it's a job completion
        const notification = data.content as
          | { type?: string; payload?: Record<string, unknown> | null }
          | undefined;
        if (notification?.type === 'job_complete' || notification?.type === 'job_error') {
          // Refetch to get the new conversation
          fetchData();
        }
      }
    });
    return unsubscribe;
  }, [subscribe, fetchData]);

  // Debounced search - filter locally
  const handleSearchChange = useCallback((value: string) => {
    setSearchQuery(value);
  }, []);

  const handleConversationClick = (conversationId: string) => {
    const tabId = createTab();
    if (!tabId) {
      return;
    }
    navigate('/', { state: { conversationId, tabId } });
  };

  const handleDeleteConversation = (e: React.MouseEvent, conversationId: string) => {
    e.stopPropagation();
    send({ type: 'delete_conversation', conversation_id: conversationId });
  };

  // Filter by selected job and search query
  const filteredConversations = conversations.filter((c) => {
    if (selectedJobId && c.job_id !== selectedJobId) {
      return false;
    }
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      const titleMatch = c.title.toLowerCase().includes(query);
      const jobName = c.job_name || jobs[c.job_id]?.name || '';
      const jobMatch = jobName.toLowerCase().includes(query);
      return titleMatch || jobMatch;
    }
    return true;
  });

  // Get unique jobs from conversations
  const uniqueJobIds = [...new Set(conversations.map((c) => c.job_id))];

  const getRelativeDateGroup = (timestamp: number): string => {
    const date = new Date(timestamp * 1000);
    const now = new Date();

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
        day: 'numeric',
      });
    }
  };

  const formatTime = (timestamp: number): string => {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    });
  };

  const renderConversations = () => {
    let lastGroup = '';

    return filteredConversations.map((convo) => {
      const currentGroup = getRelativeDateGroup(convo.created_at);
      const showHeader = currentGroup !== lastGroup;
      lastGroup = currentGroup;
      const jobName = convo.job_name || jobs[convo.job_id]?.name || 'Unknown Job';

      return (
        <React.Fragment key={convo.id}>
          {showHeader && (
            <div className="task-results-date-separator">
              <span>{currentGroup}</span>
            </div>
          )}
          <div
            className="task-results-list-item"
            onClick={() => handleConversationClick(convo.id)}
          >
            <div className="task-results-list-item-content">
              <div className="task-results-list-item-title">{convo.title}</div>
              <div className="task-results-list-item-job">
                <span className="task-badge">{jobName}</span>
              </div>
            </div>
            <div className="task-results-list-item-date-section">
              <button
                type="button"
                className="task-results-delete-btn"
                onClick={(e) => handleDeleteConversation(e, convo.id)}
                title="Delete result"
                aria-label={`Delete ${convo.title}`}
              >
                <XIcon size={14} />
              </button>
              <span className="task-results-list-item-time">{formatTime(convo.created_at)}</span>
            </div>
          </div>
        </React.Fragment>
      );
    });
  };

  return (
    <>
      <TitleBar setMini={setMini} />
      <div className="task-results-container">
        <div className="task-results-search-box-container">
          <form className="task-results-search-box-form" onSubmit={(e) => e.preventDefault()}>
            <input
              type="text"
              placeholder="Search task results..."
              className="task-results-search-box-input"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
            />
          </form>
        </div>

        {uniqueJobIds.length > 0 && (
          <div className="task-results-filter">
            <button
              className={`task-filter-btn ${selectedJobId === null ? 'active' : ''}`}
              onClick={() => setSelectedJobId(null)}
            >
              All Tasks
            </button>
            {uniqueJobIds.map((jobId) => {
              const job = jobs[jobId];
              return (
                <button
                  key={jobId}
                  className={`task-filter-btn ${selectedJobId === jobId ? 'active' : ''}`}
                  onClick={() => setSelectedJobId(jobId)}
                >
                  {job?.name || 'Unknown'}
                </button>
              );
            })}
          </div>
        )}

        <div className="task-results-list-container">
          {loading ? (
            <div className="task-results-empty-state">Loading results...</div>
          ) : filteredConversations.length === 0 ? (
            <div className="task-results-empty-state">
              {searchQuery
                ? 'No results match your search.'
                : selectedJobId
                  ? 'No results for this task yet.'
                  : 'No task results yet. Create a scheduled task and wait for it to run!'}
            </div>
          ) : (
            renderConversations()
          )}
        </div>
      </div>
    </>
  );
};

export default ScheduledJobsResults;
