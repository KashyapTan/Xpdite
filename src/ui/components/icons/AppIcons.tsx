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

export function RotateCcwIcon(props: AppIconProps) {
  return (
    <BaseIcon {...props}>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </BaseIcon>
  );
}
