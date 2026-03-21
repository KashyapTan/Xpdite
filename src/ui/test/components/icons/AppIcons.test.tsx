import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';

import {
  BanIcon,
  BoltIcon,
  CalendarIcon,
  CameraIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  ClipboardListIcon,
  HourglassIcon,
  MailIcon,
  MonitorIcon,
  RecordIcon,
  StopSquareIcon,
  TerminalIcon,
  XIcon,
} from '../../../components/icons/AppIcons';

describe('AppIcons', () => {
  test('renders icon without title as aria-hidden', () => {
    const { container } = render(<ChevronRightIcon />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg).not.toHaveAttribute('role');
  });

  test('renders icon with title as img role and visible title', () => {
    render(<BoltIcon title="Bolt" size={20} />);
    const icon = screen.getByRole('img', { name: 'Bolt' });
    expect(icon).toHaveAttribute('width', '20');
    expect(icon).toHaveAttribute('height', '20');
  });

  test('renders all exported icon components', () => {
    const { container } = render(
      <div>
        <ChevronDownIcon />
        <ChevronLeftIcon />
        <ChevronUpIcon />
        <CheckIcon />
        <TerminalIcon />
        <HourglassIcon />
        <XIcon />
        <BanIcon />
        <MonitorIcon />
        <CameraIcon />
        <RecordIcon />
        <StopSquareIcon />
        <CalendarIcon />
        <MailIcon />
        <ClipboardListIcon />
      </div>,
    );

    expect(container.querySelectorAll('svg').length).toBe(15);
  });
});

