/**
 * MobilePlatformBadge — Displays a platform icon/badge for mobile messaging channels.
 * 
 * Used in:
 * - Tab bar: Small badge next to tab title for mobile-originated tabs
 * - Chat messages: "via Platform" pill below user messages from mobile
 */
import React from 'react';
import type { MobilePlatform } from '../types';
import '../CSS/components/MobilePlatformBadge.css';

const PLATFORM_THEME: Record<MobilePlatform, { color: string }> = {
  telegram: {
    color: 'var(--color-brand-telegram)',
  },
  discord: {
    color: 'var(--color-brand-discord)',
  },
  whatsapp: {
    color: 'var(--color-brand-whatsapp)',
  },
};

// Platform display names
const PLATFORM_NAMES: Record<MobilePlatform, string> = {
  telegram: 'Telegram',
  discord: 'Discord',
  whatsapp: 'WhatsApp',
};

interface MobilePlatformBadgeProps {
  platform: MobilePlatform;
  /** Display mode: 'small' for tab badge, 'pill' for message indicator */
  size?: 'small' | 'pill';
  /** Optional display name to show (for pill mode) */
  displayName?: string;
  className?: string;
}

/**
 * SVG icons for each platform (simplified, monochrome versions)
 */
const TelegramIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
  </svg>
);

const DiscordIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M20.317 4.37a19.791 19.791 0 00-4.885-1.515.074.074 0 00-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 00-5.487 0 12.64 12.64 0 00-.617-1.25.077.077 0 00-.079-.037A19.736 19.736 0 003.677 4.37a.07.07 0 00-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 00.031.057 19.9 19.9 0 005.993 3.03.078.078 0 00.084-.028 14.09 14.09 0 001.226-1.994.076.076 0 00-.041-.106 13.107 13.107 0 01-1.872-.892.077.077 0 01-.008-.128 10.2 10.2 0 00.372-.292.074.074 0 01.077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 01.078.01c.12.098.246.198.373.292a.077.077 0 01-.006.127 12.299 12.299 0 01-1.873.892.077.077 0 00-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 00.084.028 19.839 19.839 0 006.002-3.03.077.077 0 00.032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 00-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
  </svg>
);

const WhatsAppIcon: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
  </svg>
);

const PlatformIcon: React.FC<{ platform: MobilePlatform; size: number }> = ({ platform, size }) => {
  switch (platform) {
    case 'telegram':
      return <TelegramIcon size={size} />;
    case 'discord':
      return <DiscordIcon size={size} />;
    case 'whatsapp':
      return <WhatsAppIcon size={size} />;
    default:
      return null;
  }
};

export const MobilePlatformBadge: React.FC<MobilePlatformBadgeProps> = ({
  platform,
  size = 'small',
  displayName,
  className = '',
}) => {
  const platformTheme = PLATFORM_THEME[platform];
  const name = PLATFORM_NAMES[platform];
  
  if (size === 'small') {
    // Small badge for tab bar - just the icon
    return (
      <span 
        className={`mobile-platform-badge mobile-platform-badge--small ${className}`}
        style={{ color: platformTheme.color }}
        title={`From ${name}`}
      >
        <PlatformIcon platform={platform} size={12} />
      </span>
    );
  }
  
  // Pill mode for message indicator
  return (
    <span 
      className={`mobile-platform-badge mobile-platform-badge--pill ${className}`}
      style={{ 
        backgroundColor: 'var(--color-surface)',
        color: platformTheme.color,
        borderColor: 'var(--color-border)',
      }}
    >
      <PlatformIcon platform={platform} size={12} />
      <span className="mobile-platform-badge__text">
        via {displayName || name}
      </span>
    </span>
  );
};

export default MobilePlatformBadge;
