/**
 * Query input component.
 *
 * Uses a chip-aware contenteditable composer so valid slash commands can
 * render inline without the old overlay/highlight workaround.
 */
import React, {
  forwardRef,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import SlashCommandMenu from '../chat/SlashCommandMenu';
import { X_ICON_PATHS } from '../icons/iconPaths';
import { api } from '../../services/api';
import type { Skill } from '../../types';
import '../../CSS/SlashCommandChips.css';

interface QueryInputProps {
  query: string;
  placeholder: string;
  canSubmit: boolean;
  onQueryChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  onStopStreaming: () => void;
}

type QuerySegment =
  | { type: 'text'; text: string }
  | { type: 'chip'; command: string; skillName: string };

type SlashTrigger = {
  start: number;
  end: number;
  searchTerm: string;
};

const COMMAND_TOKEN_PATTERN = /(?<!\S)\/([a-zA-Z0-9_-]+)(?=\s|$)/g;
const COMMAND_BODY_PATTERN = /^[a-zA-Z0-9_-]*$/;
const SLASH_MENU_WIDTH = 250;

function normalizeDomLabel(value: string): string {
  return Array.from(value)
    .map((character) => {
      const codePoint = character.charCodeAt(0);
      return codePoint < 0x20 || codePoint === 0x7f ? ' ' : character;
    })
    .join('')
    .replace(/\s+/g, ' ')
    .trim();
}

function mergeTextSegments(segments: QuerySegment[]): QuerySegment[] {
  const merged: QuerySegment[] = [];

  for (const segment of segments) {
    if (segment.type === 'text') {
      if (!segment.text) {
        continue;
      }

      const previous = merged[merged.length - 1];
      if (previous?.type === 'text') {
        previous.text += segment.text;
      } else {
        merged.push({ ...segment });
      }
      continue;
    }

    merged.push(segment);
  }

  return merged;
}

function serializeSegments(segments: QuerySegment[]): string {
  return segments
    .map((segment) =>
      segment.type === 'chip' ? `/${segment.command}` : segment.text,
    )
    .join('');
}

function getSegmentOffset(segments: QuerySegment[], targetIndex: number): number {
  let offset = 0;

  for (let index = 0; index < targetIndex; index += 1) {
    const segment = segments[index];
    offset +=
      segment.type === 'chip'
        ? segment.command.length + 1
        : segment.text.length;
  }

  return offset;
}

function isOffsetAtChipBoundary(
  segments: QuerySegment[],
  offset: number,
): boolean {
  let currentOffset = 0;

  for (const segment of segments) {
    if (segment.type === 'chip') {
      const chipEnd = currentOffset + segment.command.length + 1;
      if (offset > currentOffset && offset <= chipEnd) {
        return true;
      }
      currentOffset = chipEnd;
      continue;
    }

    currentOffset += segment.text.length;
  }

  return false;
}

function normalizeQuerySegments(
  query: string,
  commandMap: Map<string, Skill>,
  commandsWithLongerMatches: Set<string>,
  cursorOffset: number,
  allowEditingToken: boolean,
): QuerySegment[] {
  const segments: QuerySegment[] = [];
  let lastIndex = 0;
  COMMAND_TOKEN_PATTERN.lastIndex = 0;
  const matcher = COMMAND_TOKEN_PATTERN;
  let match: RegExpExecArray | null = null;

  while ((match = matcher.exec(query)) !== null) {
    const token = match[0];
    const start = match.index;
    const end = start + token.length;
    const command = match[1].toLowerCase();
    const skill = commandMap.get(command);

    if (!skill) {
      continue;
    }

    const editingThisToken =
      allowEditingToken &&
      cursorOffset > start &&
      (cursorOffset < end ||
        (cursorOffset === end &&
          commandsWithLongerMatches.has(command)));

    if (editingThisToken) {
      continue;
    }

    if (start > lastIndex) {
      segments.push({ type: 'text', text: query.slice(lastIndex, start) });
    }

    segments.push({
      type: 'chip',
      command: skill.slash_command ?? command,
      skillName: skill.name,
    });
    lastIndex = end;
  }

  if (lastIndex < query.length) {
    segments.push({ type: 'text', text: query.slice(lastIndex) });
  }

  return mergeTextSegments(segments);
}

function getSlashTrigger(query: string, cursorOffset: number): SlashTrigger | null {
  if (cursorOffset < 0 || cursorOffset > query.length) {
    return null;
  }

  let start = cursorOffset;
  while (start > 0 && !/\s/.test(query[start - 1])) {
    start -= 1;
  }

  let end = cursorOffset;
  while (end < query.length && !/\s/.test(query[end])) {
    end += 1;
  }

  const token = query.slice(start, end);
  const typedToken = query.slice(start, cursorOffset);

  if (
    !token.startsWith('/') ||
    !typedToken.startsWith('/') ||
    !COMMAND_BODY_PATTERN.test(token.slice(1)) ||
    !COMMAND_BODY_PATTERN.test(typedToken.slice(1))
  ) {
    return null;
  }

  return {
    start,
    end,
    searchTerm: typedToken.slice(1).toLowerCase(),
  };
}

function getSelectionOffset(editor: HTMLDivElement): number {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) {
    return 0;
  }

  const range = selection.getRangeAt(0);
  if (!editor.contains(range.endContainer)) {
    return 0;
  }

  const preRange = range.cloneRange();
  preRange.selectNodeContents(editor);
  preRange.setEnd(range.endContainer, range.endOffset);

  return preRange.toString().length;
}

function restoreSelectionOffset(editor: HTMLDivElement, offset: number): void {
  const selection = window.getSelection();
  if (!selection) {
    return;
  }

  const range = document.createRange();
  let remaining = Math.max(0, offset);
  const children = Array.from(editor.childNodes);

  if (children.length === 0) {
    range.setStart(editor, 0);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    return;
  }

  for (const child of children) {
    if (child instanceof HTMLElement && child.dataset.slashChip === 'true') {
      const chipLength = Number(child.dataset.plainTextLength ?? child.textContent?.length ?? 0);

      if (remaining === 0) {
        range.setStartBefore(child);
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);
        return;
      }

      if (remaining <= chipLength) {
        range.setStartAfter(child);
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);
        return;
      }

      remaining -= chipLength;
      continue;
    }

    const textValue = child.textContent ?? '';
    if (remaining <= textValue.length) {
      const textNode = child.firstChild ?? child;
      if (textNode.nodeType === Node.TEXT_NODE) {
        range.setStart(textNode, remaining);
      } else {
        range.setStart(child, Math.min(remaining, child.childNodes.length));
      }
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      return;
    }

    remaining -= textValue.length;
  }

  range.selectNodeContents(editor);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function buildChipRemoveIcon(): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '11');
  svg.setAttribute('height', '11');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');

  for (const pathValue of X_ICON_PATHS) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', pathValue);
    svg.append(path);
  }
  return svg;
}

function buildChipNode(segment: Extract<QuerySegment, { type: 'chip' }>, index: number): HTMLSpanElement {
  const chipNode = document.createElement('span');
  chipNode.className = 'slash-command-chip query-input-chip';
  chipNode.contentEditable = 'false';
  chipNode.dataset.slashChip = 'true';
  chipNode.dataset.plainTextLength = String(`/${segment.command}`.length);
  chipNode.dataset.chipIndex = String(index);
  chipNode.title = normalizeDomLabel(segment.skillName);

  const chipTextNode = document.createElement('span');
  chipTextNode.className = 'chip-text';
  chipTextNode.textContent = `/${segment.command}`;

  const removeButton = document.createElement('button');
  removeButton.type = 'button';
  removeButton.className = 'chip-remove-btn';
  removeButton.ariaLabel = `Remove /${normalizeDomLabel(segment.command)}`;
  removeButton.dataset.chipRemove = 'true';
  removeButton.dataset.chipIndex = String(index);
  removeButton.tabIndex = -1;
  removeButton.append(buildChipRemoveIcon());

  chipNode.append(chipTextNode, removeButton);
  return chipNode;
}

function syncEditorContent(editor: HTMLDivElement, segments: QuerySegment[]): void {
  const fragment = document.createDocumentFragment();

  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    if (segment.type === 'chip') {
      fragment.append(buildChipNode(segment, index));
      continue;
    }

    if (segment.text) {
      fragment.append(document.createTextNode(segment.text));
    }
  }

  editor.replaceChildren(fragment);
}

export const QueryInput = forwardRef<HTMLDivElement, QueryInputProps>(
  (
    {
      query,
      placeholder,
      canSubmit,
      onQueryChange,
      onSubmit,
      onStopStreaming,
    },
    ref,
  ) => {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [isFocused, setIsFocused] = useState(false);
    const [selectionOffset, setSelectionOffset] = useState(query.length);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 8 });
    const [dismissedTriggerKey, setDismissedTriggerKey] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const formRef = useRef<HTMLFormElement>(null);
    const editorRef = useRef<HTMLDivElement>(null);
    const internalUpdateRef = useRef(false);
    const renderedSegmentsRef = useRef<QuerySegment[]>([]);

    const setEditorRefs = useCallback(
      (node: HTMLDivElement | null) => {
        editorRef.current = node;
        if (typeof ref === 'function') {
          ref(node);
          return;
        }

        if (ref) {
          (ref as React.MutableRefObject<HTMLDivElement | null>).current = node;
        }
      },
      [ref],
    );

    useEffect(() => {
      let isMounted = true;

      const loadSkills = async () => {
        try {
          const allSkills = await api.skillsApi.getAll();
          if (!isMounted) {
            return;
          }

          setSkills(allSkills.filter((skill) => skill.enabled && skill.slash_command));
        } catch (error) {
          console.error('Failed to load skills for slash commands', error);
        }
      };

      void loadSkills();

      return () => {
        isMounted = false;
      };
    }, []);

    const { commandMap, commandsWithLongerMatches } = useMemo(() => {
      const nextCommandMap = new Map(
        skills.flatMap((skill) =>
          skill.slash_command
            ? [[skill.slash_command.toLowerCase(), skill] as const]
            : [],
        ),
      );
      const commands = Array.from(nextCommandMap.keys()).sort(
        (left, right) => left.length - right.length,
      );
      const longerMatches = new Set<string>();

      for (let index = 0; index < commands.length; index += 1) {
        const currentCommand = commands[index];
        for (let compareIndex = index + 1; compareIndex < commands.length; compareIndex += 1) {
          if (commands[compareIndex].startsWith(currentCommand)) {
            longerMatches.add(currentCommand);
            break;
          }
        }
      }

      return {
        commandMap: nextCommandMap,
        commandsWithLongerMatches: longerMatches,
      };
    }, [skills]);

    const segments = useMemo(
      () =>
        normalizeQuerySegments(
          query,
          commandMap,
          commandsWithLongerMatches,
          selectionOffset,
          isFocused,
        ),
      [commandMap, commandsWithLongerMatches, isFocused, query, selectionOffset],
    );

    const serializedQuery = useMemo(() => serializeSegments(segments), [segments]);

    const detectedTrigger = useMemo(
      () =>
        isFocused && !isOffsetAtChipBoundary(segments, selectionOffset)
          ? getSlashTrigger(serializedQuery, selectionOffset)
          : null,
      [isFocused, segments, selectionOffset, serializedQuery],
    );

    const detectedTriggerKey = useMemo(
      () =>
        detectedTrigger
          ? `${detectedTrigger.start}:${detectedTrigger.end}:${detectedTrigger.searchTerm}:${serializedQuery}`
          : null,
      [detectedTrigger, serializedQuery],
    );

    const activeTrigger = useMemo(
      () =>
        detectedTriggerKey !== null && detectedTriggerKey === dismissedTriggerKey
          ? null
          : detectedTrigger,
      [detectedTrigger, detectedTriggerKey, dismissedTriggerKey],
    );

    const filteredSkills = useMemo(() => {
      if (!activeTrigger) {
        return [];
      }

      return skills.filter((skill) => {
        const slashCommand = skill.slash_command?.toLowerCase() ?? '';
        return (
          slashCommand.includes(activeTrigger.searchTerm) ||
          skill.name.toLowerCase().includes(activeTrigger.searchTerm)
        );
      });
    }, [activeTrigger, skills]);

    const renderedSegmentsSignature = useMemo(
      () =>
        segments
          .map((segment) =>
            segment.type === 'chip'
              ? `chip:${segment.command}:${segment.skillName}`
              : `text:${segment.text}`,
          )
          .join('\u0001'),
      [segments],
    );
    renderedSegmentsRef.current = segments;

    const updateMenuPosition = useCallback(() => {
      const editor = editorRef.current;
      const container = containerRef.current;
      const selection = window.getSelection();

      if (
        !editor ||
        !container ||
        !selection ||
        !selection.rangeCount ||
        !editor.contains(selection.anchorNode)
      ) {
        return;
      }

      const range = selection.getRangeAt(0).cloneRange();
      range.collapse(true);

      let rect = range.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) {
        rect = editor.getBoundingClientRect();
      }

      const containerRect = container.getBoundingClientRect();
      const nextLeft = Math.max(
        8,
        Math.min(rect.left - containerRect.left, containerRect.width - SLASH_MENU_WIDTH - 8),
      );

      setMenuPosition({ top: 0, left: nextLeft });
    }, []);

    useEffect(() => {
      setSelectedIndex(0);
    }, [activeTrigger?.searchTerm, filteredSkills.length]);

    useEffect(() => {
      if (internalUpdateRef.current) {
        internalUpdateRef.current = false;
        return;
      }

      setSelectionOffset(query.length);
    }, [query]);

    useLayoutEffect(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }

      syncEditorContent(editor, renderedSegmentsRef.current);
    }, [renderedSegmentsSignature]);

    useLayoutEffect(() => {
      const editor = editorRef.current;
      if (!editor || !isFocused || document.activeElement !== editor) {
        return;
      }

      restoreSelectionOffset(editor, selectionOffset);
      updateMenuPosition();
    }, [isFocused, selectionOffset, segments, updateMenuPosition]);

    const updateQueryValue = useCallback(
      (nextValue: string, nextOffset: number) => {
        internalUpdateRef.current = true;
        setSelectionOffset(nextOffset);
        setDismissedTriggerKey(null);
        onQueryChange(nextValue);
      },
      [onQueryChange],
    );

    const syncSelectionFromDom = useCallback(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }

      if (document.activeElement !== editor) {
        return;
      }

      setSelectionOffset(getSelectionOffset(editor));
      updateMenuPosition();
    }, [updateMenuPosition]);

    const handleSelectCommand = useCallback(
      (skill: Skill) => {
        if (!skill.slash_command || !activeTrigger) {
          return;
        }

        const slashCommand = `/${skill.slash_command}`;
        const nextCharacter = serializedQuery[activeTrigger.end];
        const needsTrailingSpace =
          nextCharacter === undefined || !/\s/.test(nextCharacter);
        const replacement = needsTrailingSpace
          ? `${slashCommand} `
          : slashCommand;
        const nextValue =
          serializedQuery.slice(0, activeTrigger.start) +
          replacement +
          serializedQuery.slice(activeTrigger.end);
        const nextOffset = activeTrigger.start + replacement.length;

        updateQueryValue(nextValue, nextOffset);
        requestAnimationFrame(() => {
          editorRef.current?.focus();
        });
      },
      [activeTrigger, serializedQuery, updateQueryValue],
    );

    const handleRemoveCommand = useCallback(
      (index: number) => {
        const commandSegment = segments[index];
        if (!commandSegment || commandSegment.type !== 'chip') {
          return;
        }

        const commandStart = getSegmentOffset(segments, index);
        let removalStart = commandStart;
        let removalEnd = commandStart + commandSegment.command.length + 1;
        const fullQuery = serializeSegments(segments);

        if (fullQuery[removalEnd] === ' ') {
          removalEnd += 1;
        } else if (removalStart > 0 && fullQuery[removalStart - 1] === ' ') {
          removalStart -= 1;
        }

        const nextValue =
          fullQuery.slice(0, removalStart) +
          fullQuery.slice(removalEnd);
        updateQueryValue(nextValue, Math.min(removalStart, nextValue.length));

        requestAnimationFrame(() => {
          editorRef.current?.focus();
        });
      },
      [segments, updateQueryValue],
    );

    const handleEditorInput = useCallback(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }

      const nextValue = (editor.textContent ?? '').replace(/\u00a0/g, ' ');
      const nextOffset = getSelectionOffset(editor);
      updateQueryValue(nextValue, nextOffset);
    }, [updateQueryValue]);

    const handleEditorMouseDown = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      if (target.closest('[data-chip-remove="true"]')) {
        event.preventDefault();
      }
    }, []);

    const handleEditorClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }

      const removeButton = target.closest<HTMLElement>('[data-chip-remove="true"]');
      if (!removeButton) {
        return;
      }

      event.preventDefault();
      const chipIndex = Number(removeButton.dataset.chipIndex ?? Number.NaN);
      if (Number.isNaN(chipIndex)) {
        return;
      }

      handleRemoveCommand(chipIndex);
    }, [handleRemoveCommand]);

    const handleSubmit = (e: FormEvent) => {
      e.preventDefault();
      if (!query.trim()) {
        return;
      }

      onSubmit(e);
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
      if (filteredSkills.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedIndex((previous) => (previous + 1) % filteredSkills.length);
          return;
        }

        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedIndex(
            (previous) => (previous - 1 + filteredSkills.length) % filteredSkills.length,
          );
          return;
        }

        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          handleSelectCommand(filteredSkills[selectedIndex]);
          return;
        }

        if (e.key === 'Escape') {
          e.preventDefault();
          if (detectedTriggerKey) {
            setDismissedTriggerKey(detectedTriggerKey);
          }
          return;
        }
      }

      if (e.key === 'Enter') {
        e.preventDefault();
        if (!e.shiftKey) {
          formRef.current?.requestSubmit();
        }
      }
    };

    return (
      <div
        ref={containerRef}
        className="query-input-text-box-section"
        style={{ position: 'relative' }}
      >
        <SlashCommandMenu
          skills={filteredSkills}
          selectedIndex={selectedIndex}
          position={menuPosition}
          onSelect={handleSelectCommand}
          onHover={setSelectedIndex}
        />

        <form ref={formRef} onSubmit={handleSubmit} className="query-input-form">
          <div
            ref={setEditorRefs}
            className="query-input"
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-label="Query input"
            spellCheck={false}
            data-placeholder={placeholder}
            onInput={handleEditorInput}
            onKeyDown={handleKeyDown}
            onKeyUp={syncSelectionFromDom}
            onMouseDown={handleEditorMouseDown}
            onClick={handleEditorClick}
            onMouseUp={syncSelectionFromDom}
            onFocus={() => {
              setIsFocused(true);
              requestAnimationFrame(syncSelectionFromDom);
            }}
            onBlur={() => {
              setIsFocused(false);
              setDismissedTriggerKey(null);
            }}
          />
        </form>

        {!canSubmit && (
          <button
            className="stop-streaming-button"
            onClick={onStopStreaming}
            title="Stop generating"
          >
            <div className="stop-icon" />
          </button>
        )}
      </div>
    );
  },
);

QueryInput.displayName = 'QueryInput';
