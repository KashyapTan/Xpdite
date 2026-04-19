import type { ReactNode, SVGProps } from 'react';
import { BOLT_ICON_PATHS, X_ICON_PATHS } from './iconPaths';

type AppIconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  children?: ReactNode;
  size?: number;
  title?: string;
};

function BaseIcon({
  children,
  size = 16,
  strokeWidth = 2,
  title,
  ...props
}: AppIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      focusable="false"
      role={title ? 'img' : undefined}
      {...props}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export function ChevronRightIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="m9 18 6-6-6-6" />
    </BaseIcon>
  );
}

export function ChevronDownIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="m6 9 6 6 6-6" />
    </BaseIcon>
  );
}

export function ChevronLeftIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="m15 18-6-6 6-6" />
    </BaseIcon>
  );
}

export function ChevronUpIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="m18 15-6-6-6 6" />
    </BaseIcon>
  );
}

export function CheckIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M20 6 9 17l-5-5" />
    </BaseIcon>
  );
}

export function TerminalIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M12 19h8" />
      <path d="m4 17 6-6-6-6" />
    </BaseIcon>
  );
}

export function BoltIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      {BOLT_ICON_PATHS.map((pathValue) => (
        <path key={pathValue} d={pathValue} />
      ))}
    </BaseIcon>
  );
}

export function HourglassIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M5 22h14" />
      <path d="M5 2h14" />
      <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22" />
      <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2" />
    </BaseIcon>
  );
}

export function XIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      {X_ICON_PATHS.map((pathValue) => (
        <path key={pathValue} d={pathValue} />
      ))}
    </BaseIcon>
  );
}

export function BanIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 8.5 7 7" />
    </BaseIcon>
  );
}

export function MonitorIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M12 16v4" />
      <path d="M8 20h8" />
    </BaseIcon>
  );
}

export function CameraIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M4 7h3l2-2h6l2 2h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z" />
      <circle cx="12" cy="13" r="3" />
    </BaseIcon>
  );
}

export function RecordIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <circle cx="12" cy="12" r="7" fill="currentColor" stroke="none" />
    </BaseIcon>
  );
}

export function StopSquareIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none" />
    </BaseIcon>
  );
}

export function CalendarIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M8 2v4" />
      <path d="M16 2v4" />
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M3 10h18" />
    </BaseIcon>
  );
}

export function MailIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </BaseIcon>
  );
}

export function ClipboardListIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <path d="M9 11h6" />
      <path d="M9 15h6" />
      <path d="M9 19h4" />
    </BaseIcon>
  );
}

export function CopyIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" />
    </BaseIcon>
  );
}

export function PencilIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M12 20h9" />
      <path d="m16.5 3.5 4 4" />
      <path d="M4 20l4.5-1 9.5-9.5a2.12 2.12 0 1 0-3-3L5.5 16 4 20Z" />
    </BaseIcon>
  );
}

export function ViewIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
      <circle cx="12" cy="12" r="3" />
    </BaseIcon>
  );
}

export function CodeXmlIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="m18 16 4-4-4-4" />
      <path d="m6 8-4 4 4 4" />
      <path d="m14.5 4-5 16" />
    </BaseIcon>
  );
}

export function TrashIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </BaseIcon>
  );
}

export function SquareArrowOutUpRightIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M21 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h6" />
      <path d="m21 3-9 9" />
      <path d="M15 3h6v6" />
    </BaseIcon>
  );
}

export function RotateCcwIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </BaseIcon>
  );
}

export function ConnectionsTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M12 3v17a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6a1 1 0 0 1-1 1H3" />
      <path d="M16 19h6" />
      <path d="M19 22v-6" />
    </BaseIcon>
  );
}

export function ToolsTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z" />
    </BaseIcon>
  );
}

export function SkillsTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M15 12h-5" />
      <path d="M15 8h-5" />
      <path d="M19 17V5a2 2 0 0 0-2-2H4" />
      <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" />
    </BaseIcon>
  );
}

export function MemoryTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M12 12v-2" />
      <path d="M12 18v-2" />
      <path d="M16 12v-2" />
      <path d="M16 18v-2" />
      <path d="M2 11h1.5" />
      <path d="M20 18v-2" />
      <path d="M20.5 11H22" />
      <path d="M4 18v-2" />
      <path d="M8 12v-2" />
      <path d="M8 18v-2" />
      <rect x="2" y="6" width="20" height="10" rx="2" />
    </BaseIcon>
  );
}

export function ArtifactsTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" />
      <path d="M14 2v5a1 1 0 0 0 1 1h5" />
      <path d="M10 9H8" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
    </BaseIcon>
  );
}

export function TasksTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M11 10v4h4" />
      <path d="m11 14 1.535-1.605a5 5 0 0 1 8 1.5" />
      <path d="M16 2v4" />
      <path d="m21 18-1.535 1.605a5 5 0 0 1-8-1.5" />
      <path d="M21 22v-4h-4" />
      <path d="M21 8.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4.3" />
      <path d="M3 10h4" />
      <path d="M8 2v4" />
    </BaseIcon>
  );
}

export function MeetingTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M2 10v3" />
      <path d="M6 6v11" />
      <path d="M10 3v18" />
      <path d="M14 8v7" />
      <path d="M18 5v13" />
      <path d="M22 10v3" />
    </BaseIcon>
  );
}

export function SubAgentsTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M12 8V4H8" />
      <rect x="4" y="8" width="16" height="12" rx="2" />
      <path d="M2 14h2" />
      <path d="M20 14h2" />
      <path d="M15 13v2" />
      <path d="M9 13v2" />
    </BaseIcon>
  );
}

export function MobileTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
      <path d="M12 18h.01" />
    </BaseIcon>
  );
}

export function PromptTabIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M15 8a1 1 0 0 1-1-1V2a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8z" />
      <path d="M20 8v12a2 2 0 0 1-2 2h-4.182" />
      <path d="m3.305 19.53.923-.382" />
      <path d="M4 10.592V4a2 2 0 0 1 2-2h8" />
      <path d="m4.228 16.852-.924-.383" />
      <path d="m5.852 15.228-.383-.923" />
      <path d="m5.852 20.772-.383.924" />
      <path d="m8.148 15.228.383-.923" />
      <path d="m8.53 21.696-.382-.924" />
      <path d="m9.773 16.852.922-.383" />
      <path d="m9.773 19.148.922.383" />
      <circle cx="7" cy="18" r="3" />
    </BaseIcon>
  );
}
