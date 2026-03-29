import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import { useWebSocket } from '../contexts/WebSocketContext';
import '../CSS/NotificationBell.css';

interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  payload: Record<string, unknown> | null;
  created_at: number;
}

const NotificationBell: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  // Subscribe to real-time notification updates
  const { subscribe } = useWebSocket();

  // Fetch notifications on mount
  useEffect(() => {
    fetchNotifications();
  }, []);

  // Handle real-time notification updates via WebSocket
  useEffect(() => {
    const unsubscribe = subscribe((message) => {
      if (message.type === 'notification_added') {
        // A new notification was created - refresh the list
        fetchNotifications();
      } else if (message.type === 'notification_dismissed') {
        // A notification was dismissed
        const data = message.content as { id?: string } | undefined;
        if (data?.id) {
          setNotifications((prev) => prev.filter((n) => n.id !== data.id));
          setUnreadCount((prev) => Math.max(0, prev - 1));
        }
      } else if (message.type === 'notifications_cleared') {
        // All notifications cleared
        setNotifications([]);
        setUnreadCount(0);
      }
    });

    return unsubscribe;
  }, [subscribe]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const fetchNotifications = async () => {
    try {
      setIsLoading(true);
      const data = await api.getNotifications();
      setNotifications(data.notifications);
      setUnreadCount(data.unread_count);
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDismiss = async (e: React.MouseEvent, notificationId: string) => {
    e.stopPropagation();
    try {
      await api.dismissNotification(notificationId);
      setNotifications((prev) => prev.filter((n) => n.id !== notificationId));
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (error) {
      console.error('Failed to dismiss notification:', error);
    }
  };

  const handleDismissAll = async () => {
    try {
      await api.dismissAllNotifications();
      setNotifications([]);
      setUnreadCount(0);
    } catch (error) {
      console.error('Failed to dismiss all notifications:', error);
    }
  };

  const handleNotificationClick = useCallback(
    (notification: Notification) => {
      // Parse the payload to see if there's a link to navigate to
      if (notification.payload) {
        if (notification.payload.conversation_id) {
          // Navigate to the conversation
          setIsOpen(false);
          navigate(`/?conversation=${String(notification.payload.conversation_id)}`);
          return;
        }
        if (notification.payload.job_id) {
          // Navigate to the job results page
          setIsOpen(false);
          navigate('/scheduled-jobs');
          return;
        }
      }
      // Default: just close the dropdown
      setIsOpen(false);
    },
    [navigate]
  );

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getNotificationIcon = (type: string) => {
    switch (type) {
      case 'job_complete':
        return (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
        );
      case 'job_error':
        return (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="15" y1="9" x2="9" y2="15" />
            <line x1="9" y1="9" x2="15" y2="15" />
          </svg>
        );
      case 'tab_completed':
        return (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        );
      default:
        return (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
        );
    }
  };

  return (
    <div className="notification-bell-container" ref={dropdownRef}>
      <button
        className="notification-bell-button"
        onClick={() => setIsOpen(!isOpen)}
        title={unreadCount > 0 ? `${unreadCount} notifications` : 'No notifications'}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="notification-bell-icon"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span className="notification-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
        )}
      </button>

      {isOpen && (
        <div className="notification-dropdown">
          <div className="notification-dropdown-header">
            <span className="notification-dropdown-title">Notifications</span>
            {notifications.length > 0 && (
              <button className="notification-clear-all" onClick={handleDismissAll}>
                Clear all
              </button>
            )}
          </div>

          <div className="notification-dropdown-content">
            {isLoading ? (
              <div className="notification-empty">Loading...</div>
            ) : notifications.length === 0 ? (
              <div className="notification-empty">No notifications</div>
            ) : (
              notifications.map((notification) => (
                <div
                  key={notification.id}
                  className={`notification-item notification-type-${notification.type}`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div className="notification-item-icon">{getNotificationIcon(notification.type)}</div>
                  <div className="notification-item-content">
                    <div className="notification-item-title">{notification.title}</div>
                    <div className="notification-item-body">{notification.body}</div>
                    <div className="notification-item-time">{formatTime(notification.created_at)}</div>
                  </div>
                  <button
                    className="notification-item-dismiss"
                    onClick={(e) => handleDismiss(e, notification.id)}
                    title="Dismiss"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>

          {notifications.length > 0 && (
            <div className="notification-dropdown-footer">
              <button
                className="notification-view-all"
                onClick={() => {
                  setIsOpen(false);
                  navigate('/scheduled-jobs');
                }}
              >
                View all job results
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationBell;
