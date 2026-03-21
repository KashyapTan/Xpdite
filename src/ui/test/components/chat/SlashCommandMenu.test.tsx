import { describe, expect, test, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SlashCommandMenu from '../../../components/chat/SlashCommandMenu';
import type { Skill } from '../../../types';

const skills: Skill[] = [
  {
    name: 'terminal',
    description: 'Run shell commands',
    slash_command: 'terminal',
    trigger_servers: ['terminal'],
    version: '1.0.0',
    source: 'builtin',
    enabled: true,
    overridden_by_user: false,
    folder_path: '/skills/terminal',
  },
  {
    name: 'filesystem',
    description: 'Read files',
    slash_command: 'fs',
    trigger_servers: ['filesystem'],
    version: '1.0.0',
    source: 'builtin',
    enabled: true,
    overridden_by_user: false,
    folder_path: '/skills/filesystem',
  },
];

describe('SlashCommandMenu', () => {
  test('returns null when skills list is empty', () => {
    const { container } = render(
      <SlashCommandMenu
        skills={[]}
        selectedIndex={0}
        onHover={() => {}}
        onSelect={() => {}}
        position={{ top: 0, left: 50 }}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  test('renders skill entries and selected style', () => {
    render(
      <SlashCommandMenu
        skills={skills}
        selectedIndex={1}
        onHover={() => {}}
        onSelect={() => {}}
        position={{ top: 0, left: 88 }}
      />,
    );

    expect(screen.getByText('Skills')).toBeInTheDocument();
    expect(screen.getByText('/terminal')).toBeInTheDocument();
    expect(screen.getByText('/fs')).toBeInTheDocument();
    expect(screen.getByText('filesystem').closest('button')).toHaveClass('selected');
    expect(screen.getByText('terminal').closest('button')).not.toHaveClass('selected');
  });

  test('calls onSelect with the chosen skill', () => {
    const onSelect = vi.fn();
    render(
      <SlashCommandMenu
        skills={skills}
        selectedIndex={0}
        onHover={() => {}}
        onSelect={onSelect}
        position={{ top: 0, left: 12 }}
      />,
    );

    fireEvent.click(screen.getByText('filesystem').closest('button')!);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(skills[1]);
  });

  test('calls onHover with hovered item index', () => {
    const onHover = vi.fn();
    render(
      <SlashCommandMenu
        skills={skills}
        selectedIndex={0}
        onHover={onHover}
        onSelect={() => {}}
        position={{ top: 0, left: 120 }}
      />,
    );

    fireEvent.mouseEnter(screen.getByText('filesystem').closest('button')!);
    expect(onHover).toHaveBeenCalledWith(1);
  });

  test('prevents default on menu mouse down to keep editor focus', () => {
    const { container } = render(
      <SlashCommandMenu
        skills={skills}
        selectedIndex={0}
        onHover={() => {}}
        onSelect={() => {}}
        position={{ top: 0, left: 42 }}
      />,
    );

    const menu = container.querySelector('.slash-command-menu') as HTMLDivElement;
    const event = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    const prevented = !menu.dispatchEvent(event);

    expect(prevented).toBe(true);
  });

  test('applies horizontal menu position from props', () => {
    const { container } = render(
      <SlashCommandMenu
        skills={skills}
        selectedIndex={0}
        onHover={() => {}}
        onSelect={() => {}}
        position={{ top: 999, left: 133 }}
      />,
    );

    const menu = container.querySelector('.slash-command-menu');
    expect(menu).toHaveStyle({ left: '133px' });
    expect(menu).toHaveStyle({ bottom: 'calc(100% + 10px)' });
  });
});
