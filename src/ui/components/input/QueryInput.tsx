/**
 * Query input component.
 *
 * Uses a chip-aware contenteditable composer so valid slash commands can
 * render inline without the old overlay/highlight workaround.
 * 
 * Supports:
 * - Slash commands (/) - skills
 * - Model selection (/model)
 * - File attachments (@) - files from filesystem
 */
import React, {
  forwardRef,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  lazy,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { X_ICON_PATHS } from '../icons/iconPaths';
import type { Skill } from '../../types';
import type { FileEntry } from '../../services/api';
import '../../CSS/input/SlashCommandChips.css';

const SlashCommandMenu = lazy(() => import('../chat/SlashCommandMenu'));
const ModelCommandMenu = lazy(() => import('../chat/ModelCommandMenu'));
const FilePickerMenu = lazy(() => import('./FilePickerMenu'));
let queryInputMenusWarmupPromise: Promise<unknown> | null = null;

function warmQueryInputMenus() {
  if (!queryInputMenusWarmupPromise) {
    queryInputMenusWarmupPromise = Promise.all([
      import('../chat/SlashCommandMenu'),
      import('../chat/ModelCommandMenu'),
      import('./FilePickerMenu'),
    ]);
  }

  return queryInputMenusWarmupPromise;
}

interface QueryInputProps {
  query: string;
  placeholder: string;
  canSubmit: boolean;
  enabledModels: string[];
  onAttachedFilesChange?: (files: QueryInputAttachedFile[]) => void;
  onQueryChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  onStopStreaming: () => void;
  onSelectModel: (model: string) => void;
}

export type QueryInputAttachedFile = {
  name: string;
  path: string;
};

type QuerySegment =
  | { type: 'text'; text: string }
  | { type: 'chip'; command: string; skillName: string }
  | { type: 'file_chip'; name: string; path: string };

type SlashTrigger = {
  start: number;
  end: number;
  searchTerm: string;
};

type ModelTrigger = {
  start: number;
  end: number;
  searchTerm: string;
};

type FileTrigger = {
  start: number;
  end: number;
  searchTerm: string;
};

const COMMAND_BODY_PATTERN = /^[a-zA-Z0-9_:-]*$/;
const FILE_TRIGGER_BODY_PATTERN = /^[^\s@]*$/;
const FILE_MENU_WIDTH = 320;
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
    .map((segment) => {
      if (segment.type === 'chip') {
        return `/${segment.command}`;
      }
      if (segment.type === 'file_chip') {
        return `@${segment.name}`;
      }
      return segment.text;
    })
    .join('');
}

function getSegmentOffset(segments: QuerySegment[], targetIndex: number): number {
  let offset = 0;

  for (let index = 0; index < targetIndex; index += 1) {
    const segment = segments[index];
    offset +=
      segment.type === 'chip'
        ? segment.command.length + 1
        : segment.type === 'file_chip'
          ? segment.name.length + 1
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
    if (segment.type === 'chip' || segment.type === 'file_chip') {
      const chipLength = segment.type === 'chip' ? segment.command.length + 1 : segment.name.length + 1;
      const chipEnd = currentOffset + chipLength;
      if (offset > currentOffset && offset <= chipEnd) {
        return true;
      }
      currentOffset = chipEnd;
      continue;
    }

    if (segment.type === 'text') {
      currentOffset += segment.text.length;
    }
  }

  return false;
}

function normalizeQuerySegments(
  query: string,
  commandMap: Map<string, Skill>,
  commandsWithLongerMatches: Set<string>,
  attachedFileMap: Map<string, string>,
  cursorOffset: number,
  allowEditingToken: boolean,
): QuerySegment[] {
  const segments: QuerySegment[] = [];
  const attachedNames = Array.from(attachedFileMap.keys()).sort(
    (left, right) => right.length - left.length,
  );

  let cursor = 0;
  while (cursor < query.length) {
    let tokenStart = -1;
    for (let index = cursor; index < query.length; index += 1) {
      const character = query[index];
      if (character !== '/' && character !== '@') {
        continue;
      }
      if (index > 0 && !/\s/.test(query[index - 1])) {
        continue;
      }
      tokenStart = index;
      break;
    }

    if (tokenStart === -1) {
      segments.push({ type: 'text', text: query.slice(cursor) });
      break;
    }

    if (tokenStart > cursor) {
      segments.push({ type: 'text', text: query.slice(cursor, tokenStart) });
    }

    const prefix = query[tokenStart];

    if (prefix === '/') {
      let tokenEnd = tokenStart + 1;
      while (tokenEnd < query.length && !/\s/.test(query[tokenEnd])) {
        tokenEnd += 1;
      }

      const body = query.slice(tokenStart + 1, tokenEnd);
      const token = `/${body}`;
      const command = body.toLowerCase();
      const skill = commandMap.get(command);
      const editingThisToken =
        allowEditingToken &&
        cursorOffset > tokenStart &&
        (cursorOffset < tokenEnd ||
          (cursorOffset === tokenEnd && commandsWithLongerMatches.has(command)));

      if (
        body &&
        COMMAND_BODY_PATTERN.test(body) &&
        !editingThisToken &&
        skill
      ) {
        segments.push({
          type: 'chip',
          command: skill.slash_command ?? command,
          skillName: skill.name,
        });
      } else {
        segments.push({ type: 'text', text: token });
      }

      cursor = tokenEnd;
      continue;
    }

    let matchedFileName: string | null = null;
    let matchedFileEnd = tokenStart + 1;

    for (const name of attachedNames) {
      if (!name) {
        continue;
      }
      if (!query.startsWith(name, tokenStart + 1)) {
        continue;
      }

      const candidateEnd = tokenStart + 1 + name.length;
      if (candidateEnd < query.length && !/\s/.test(query[candidateEnd])) {
        continue;
      }

      matchedFileName = name;
      matchedFileEnd = candidateEnd;
      break;
    }

    if (matchedFileName) {
      const attachedPath = attachedFileMap.get(matchedFileName);
      const editingThisToken =
        allowEditingToken &&
        cursorOffset > tokenStart &&
        cursorOffset <= matchedFileEnd;

      if (!editingThisToken && attachedPath) {
        segments.push({
          type: 'file_chip',
          name: matchedFileName,
          path: attachedPath,
        });
      } else {
        segments.push({
          type: 'text',
          text: query.slice(tokenStart, matchedFileEnd),
        });
      }

      cursor = matchedFileEnd;
      continue;
    }

    let fallbackEnd = tokenStart + 1;
    while (fallbackEnd < query.length && !/\s/.test(query[fallbackEnd])) {
      fallbackEnd += 1;
    }
    segments.push({
      type: 'text',
      text: query.slice(tokenStart, fallbackEnd),
    });
    cursor = fallbackEnd;
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

/**
 * Detects when the user is typing `/model` or `/model <filter>`.
 * Returns a ModelTrigger if the cursor is within or after `/model`.
 * The searchTerm is the text after `/model ` (the filter for model names).
 * 
 * Algorithm:
 * 1. Walk backward from cursor to find the start of the current segment
 *    - Stop at newlines (each line is independent)
 *    - Stop at whitespace UNLESS we're in the middle of `/model <filter>` 
 *      (checked by seeing if text before whitespace ends with `/model`)
 * 2. Check if the segment from start to cursor matches `/model` pattern
 * 3. Calculate the end position by extending forward to cover any filter text
 * 4. Return the trigger with start, end, and the filter text as searchTerm
 * 
 * Examples:
 * - `/model` with cursor at end → searchTerm: ''
 * - `/model qw` with cursor at end → searchTerm: 'qw'
 * - `hello /model gpt` with cursor at end → searchTerm: 'gpt'
 * - `/mod` → null (incomplete, doesn't match /model)
 */
function getModelTrigger(query: string, cursorOffset: number): ModelTrigger | null {
  if (cursorOffset < 0 || cursorOffset > query.length) {
    return null;
  }

  // Step 1: Walk backward from cursor to find segment start
  // The segment should start at beginning of input, after a newline, or at the `/model` command
  let start = cursorOffset;
  while (start > 0 && query[start - 1] !== '\n') {
    // When we hit whitespace, check if we're in a `/model <filter>` pattern
    // If the text before this whitespace ends with `/model`, keep walking back
    // Otherwise, we've found the start of a new segment
    if (/\s/.test(query[start - 1])) {
      const precedingText = query.slice(0, start - 1).trimEnd();
      if (!precedingText.toLowerCase().endsWith('/model')) {
        break;
      }
    }
    start -= 1;
  }

  // Step 2: Check if segment matches `/model` pattern
  const segment = query.slice(start, cursorOffset);
  // Regex: `/model` optionally followed by whitespace and filter text
  // Group 1: whitespace after /model (to detect if filter mode)
  // Group 2: filter text after whitespace
  const match = segment.match(/^\/model(?:(\s+)(.*))?$/i);
  if (!match) {
    return null;
  }

  // Step 3: Calculate end position
  // First, extend to end of current word (if cursor is mid-word)
  let end = cursorOffset;
  while (end < query.length && !/[\s\n]/.test(query[end])) {
    end += 1;
  }

  // If there's filter content (match[1] is the whitespace), extend to cover all filter text
  if (match[1]) {
    while (end < query.length && query[end] !== '\n') {
      if (/\s/.test(query[end])) {
        // Only continue if non-space text follows
        const rest = query.slice(end).match(/^\s+\S/);
        if (!rest) break;
      }
      end += 1;
    }
    // Remove trailing whitespace from end position
    while (end > cursorOffset && /\s/.test(query[end - 1])) {
      end -= 1;
    }
  }

  // Step 4: Return trigger with extracted searchTerm
  return {
    start,
    end,
    searchTerm: (match[2] ?? '').toLowerCase().trim(),
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

function getFileTrigger(query: string, cursorOffset: number): FileTrigger | null {
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
    !token.startsWith('@') ||
    !typedToken.startsWith('@') ||
    !FILE_TRIGGER_BODY_PATTERN.test(token.slice(1)) ||
    !FILE_TRIGGER_BODY_PATTERN.test(typedToken.slice(1))
  ) {
    return null;
  }

  return {
    start,
    end,
    searchTerm: typedToken.slice(1).toLowerCase(),
  };
}

function buildFileChipNode(segment: Extract<QuerySegment, { type: 'file_chip' }>, index: number): HTMLSpanElement {
  const chipNode = document.createElement('span');
  chipNode.className = 'slash-command-chip query-input-chip';
  chipNode.contentEditable = 'false';
  chipNode.dataset.slashChip = 'true';
  chipNode.dataset.plainTextLength = String(`@${segment.name}`.length);
  chipNode.dataset.chipIndex = String(index);
  chipNode.title = normalizeDomLabel(segment.path);

  const chipTextNode = document.createElement('span');
  chipTextNode.className = 'chip-text';
  chipTextNode.textContent = `@${segment.name}`;

  const removeButton = document.createElement('button');
  removeButton.type = 'button';
  removeButton.className = 'chip-remove-btn';
  removeButton.ariaLabel = `Remove @${normalizeDomLabel(segment.name)}`;
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

    if (segment.type === 'file_chip') {
      fragment.append(buildFileChipNode(segment, index));
      continue;
    }

    if (segment.type === 'text' && segment.text) {
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
      enabledModels,
      onAttachedFilesChange,
      onQueryChange,
      onSubmit,
      onStopStreaming,
      onSelectModel,
    },
    ref,
  ) => {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [isFocused, setIsFocused] = useState(false);
    const [selectionOffset, setSelectionOffset] = useState(query.length);
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 8 });
    const [dismissedTriggerKey, setDismissedTriggerKey] = useState<string | null>(null);
    // Model menu state
    const [modelSelectedIndex, setModelSelectedIndex] = useState(0);
    const [modelMenuPosition, setModelMenuPosition] = useState({ top: 0, left: 8 });
    const [dismissedModelTriggerKey, setDismissedModelTriggerKey] = useState<string | null>(null);
    const [fileSelectedIndex, setFileSelectedIndex] = useState(0);
    const [fileMenuPosition, setFileMenuPosition] = useState({ top: 0, left: 8 });
    const [dismissedFileTriggerKey, setDismissedFileTriggerKey] = useState<string | null>(null);
    const [pickerEntries, setPickerEntries] = useState<FileEntry[]>([]);
    const attachedFileMapRef = useRef<Map<string, string>>(new Map());

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
          const { api } = await import('../../services/api');
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

    useEffect(() => {
      const warm = () => {
        void warmQueryInputMenus();
      };

      if (typeof window.requestIdleCallback === 'function') {
        const idleId = window.requestIdleCallback(warm, { timeout: 2500 });
        return () => {
          window.cancelIdleCallback?.(idleId);
        };
      }

      const timeoutId = window.setTimeout(warm, 1200);
      return () => {
        window.clearTimeout(timeoutId);
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
          attachedFileMapRef.current,
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

    // Model command trigger detection
    const detectedModelTrigger = useMemo(
      () =>
        isFocused && !isOffsetAtChipBoundary(segments, selectionOffset)
          ? getModelTrigger(serializedQuery, selectionOffset)
          : null,
      [isFocused, segments, selectionOffset, serializedQuery],
    );

    const detectedModelTriggerKey = useMemo(
      () =>
        detectedModelTrigger
          ? `model:${detectedModelTrigger.start}:${detectedModelTrigger.end}:${detectedModelTrigger.searchTerm}:${serializedQuery}`
          : null,
      [detectedModelTrigger, serializedQuery],
    );

    const activeModelTrigger = useMemo(
      () =>
        detectedModelTriggerKey !== null && detectedModelTriggerKey === dismissedModelTriggerKey
          ? null
          : detectedModelTrigger,
      [detectedModelTrigger, detectedModelTriggerKey, dismissedModelTriggerKey],
    );

    const filteredModels = useMemo(() => {
      if (!activeModelTrigger) {
        return [];
      }

      return enabledModels.filter((model) =>
        model.toLowerCase().includes(activeModelTrigger.searchTerm),
      );
    }, [activeModelTrigger, enabledModels]);

    const detectedFileTrigger = useMemo(
      () =>
        isFocused && !isOffsetAtChipBoundary(segments, selectionOffset)
          ? getFileTrigger(serializedQuery, selectionOffset)
          : null,
      [isFocused, segments, selectionOffset, serializedQuery],
    );

    const detectedFileTriggerKey = useMemo(
      () =>
        detectedFileTrigger
          ? `file:${detectedFileTrigger.start}:${detectedFileTrigger.end}:${detectedFileTrigger.searchTerm}:${serializedQuery}`
          : null,
      [detectedFileTrigger, serializedQuery],
    );

    const activeFileTrigger = useMemo(
      () =>
        detectedFileTriggerKey !== null && detectedFileTriggerKey === dismissedFileTriggerKey
          ? null
          : detectedFileTrigger,
      [detectedFileTrigger, detectedFileTriggerKey, dismissedFileTriggerKey],
    );

    // Check if model menu should take priority over slash command menu
    // Model menu takes priority when /model is detected
    const showModelMenu = filteredModels.length > 0;
    const showFileMenu = activeFileTrigger !== null && !showModelMenu;
    const showSlashMenu = filteredSkills.length > 0 && !showModelMenu && !showFileMenu;
    const menuActive = showSlashMenu || showModelMenu || showFileMenu;
    const hasChipSegments = useMemo(
      () => segments.some((segment) => segment.type === 'chip' || segment.type === 'file_chip'),
      [segments],
    );
    const needsSelectionTracking = hasChipSegments || menuActive || serializedQuery.includes('/') || serializedQuery.includes('@');

    const renderedSegmentsSignature = useMemo(
      () =>
        segments
          .map((segment) =>
            segment.type === 'chip'
              ? `chip:${segment.command}:${segment.skillName}`
              : segment.type === 'file_chip'
                ? `file:${segment.name}:${segment.path}`
                : `text:${segment.text}`,
          )
          .join('\u0001'),
      [segments],
    );
    renderedSegmentsRef.current = segments;

    const updateMenuPosition = useCallback(() => {
      if (!menuActive) {
        return;
      }

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
      const nextFileLeft = Math.max(
        8,
        Math.min(rect.left - containerRect.left, containerRect.width - FILE_MENU_WIDTH - 8),
      );

      setMenuPosition((previous) => (
        previous.left === nextLeft ? previous : { top: 0, left: nextLeft }
      ));
      setModelMenuPosition((previous) => (
        previous.left === nextLeft ? previous : { top: 0, left: nextLeft }
      ));
      setFileMenuPosition((previous) => (
        previous.left === nextFileLeft ? previous : { top: 0, left: nextFileLeft }
      ));
    }, [menuActive]);

    useEffect(() => {
      setSelectedIndex(0);
    }, [activeTrigger?.searchTerm, filteredSkills.length]);

    // Reset model selection index when model trigger or filtered models change
    useEffect(() => {
      setModelSelectedIndex(0);
    }, [activeModelTrigger?.searchTerm, filteredModels.length]);

    useEffect(() => {
      setFileSelectedIndex(0);
    }, [activeFileTrigger?.searchTerm]);

    useEffect(() => {
      const files = segments
        .filter((segment): segment is Extract<QuerySegment, { type: 'file_chip' }> => segment.type === 'file_chip')
        .map((segment) => ({ name: segment.name, path: segment.path }));
      onAttachedFilesChange?.(files);
    }, [onAttachedFilesChange, segments]);

    useEffect(() => {
      if (query.trim().length === 0) {
        attachedFileMapRef.current.clear();
      }
    }, [query]);

    useEffect(() => {
      if (internalUpdateRef.current) {
        internalUpdateRef.current = false;
        return;
      }

      if (!needsSelectionTracking) {
        return;
      }

      setSelectionOffset(query.length);
    }, [needsSelectionTracking, query]);

    useLayoutEffect(() => {
      const editor = editorRef.current;
      if (!editor) {
        return;
      }

      if (!hasChipSegments) {
        const currentText = (editor.textContent ?? '').replace(/\u00a0/g, ' ');
        if (currentText === serializedQuery) {
          return;
        }
      }

      syncEditorContent(editor, renderedSegmentsRef.current);
    }, [hasChipSegments, renderedSegmentsSignature, serializedQuery]);

    useLayoutEffect(() => {
      const editor = editorRef.current;
      if (!editor || !isFocused || document.activeElement !== editor) {
        return;
      }

      if (!needsSelectionTracking) {
        return;
      }

      restoreSelectionOffset(editor, selectionOffset);
      if (menuActive) {
        updateMenuPosition();
      }
    }, [isFocused, menuActive, needsSelectionTracking, selectionOffset, updateMenuPosition]);

    const updateQueryValue = useCallback(
      (nextValue: string, nextOffset: number, trackSelection: boolean = true) => {
        internalUpdateRef.current = trackSelection;
        if (trackSelection) {
          setSelectionOffset(nextOffset);
        }
        setDismissedTriggerKey(null);
        setDismissedModelTriggerKey(null);
        setDismissedFileTriggerKey(null);
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

      if (!needsSelectionTracking) {
        return;
      }

      const nextOffset = getSelectionOffset(editor);
      setSelectionOffset((previous) => (previous === nextOffset ? previous : nextOffset));
      if (menuActive) {
        updateMenuPosition();
      }
    }, [menuActive, needsSelectionTracking, updateMenuPosition]);

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

    /**
     * Handles model selection from the model command menu.
     * Switches the model and removes /model from the input.
     */
    const handleSelectModel = useCallback(
      (model: string) => {
        if (!activeModelTrigger) {
          return;
        }

        // Switch the model
        onSelectModel(model);

        // Remove /model and any filter text from input
        const nextValue =
          serializedQuery.slice(0, activeModelTrigger.start) +
          serializedQuery.slice(activeModelTrigger.end);
        const trimmedValue = nextValue.trimStart();
        const offsetAdjustment = nextValue.length - trimmedValue.length;
        const nextOffset = Math.max(0, activeModelTrigger.start - offsetAdjustment);

        updateQueryValue(trimmedValue, Math.min(nextOffset, trimmedValue.length));
        requestAnimationFrame(() => {
          editorRef.current?.focus();
        });
      },
      [activeModelTrigger, serializedQuery, onSelectModel, updateQueryValue],
    );

    const handleRemoveCommand = useCallback(
      (index: number) => {
        const commandSegment = segments[index];
        if (!commandSegment || (commandSegment.type !== 'chip' && commandSegment.type !== 'file_chip')) {
          return;
        }

        if (commandSegment.type === 'file_chip') {
          attachedFileMapRef.current.delete(commandSegment.name);
        }

        const commandStart = getSegmentOffset(segments, index);
        let removalStart = commandStart;
        const chipLength = commandSegment.type === 'chip'
          ? commandSegment.command.length + 1
          : commandSegment.name.length + 1;
        let removalEnd = commandStart + chipLength;
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
      const trackSelection = hasChipSegments || nextValue.includes('/') || nextValue.includes('@');
      updateQueryValue(nextValue, nextOffset, trackSelection);
    }, [hasChipSegments, updateQueryValue]);

    const handleSelectFile = useCallback((entry: FileEntry) => {
      if (!activeFileTrigger || entry.is_directory) {
        return;
      }

      const currentFiles = segments.filter((segment): segment is Extract<QuerySegment, { type: 'file_chip' }> => segment.type === 'file_chip');
      if (currentFiles.length >= 10) {
        return;
      }
      if (currentFiles.some((file) => file.path === entry.path || file.name === entry.name)) {
        return;
      }

      attachedFileMapRef.current.set(entry.name, entry.path);
      const replacement = `@${entry.name} `;
      const nextValue =
        serializedQuery.slice(0, activeFileTrigger.start) +
        replacement +
        serializedQuery.slice(activeFileTrigger.end);
      const nextOffset = activeFileTrigger.start + replacement.length;
      updateQueryValue(nextValue, nextOffset);
      requestAnimationFrame(() => {
        editorRef.current?.focus();
      });
    }, [activeFileTrigger, segments, serializedQuery, updateQueryValue]);

    const handleFileEntriesChange = useCallback(
      (entries: FileEntry[]) => {
        setPickerEntries(entries);
      },
      [],
    );

    const handleEditorMouseDown = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target;
      if (!(target instanceof Element)) {
        return;
      }

      if (target.closest('[data-chip-remove="true"]')) {
        event.preventDefault();
      }
    }, []);

    const handleEditorClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
      const target = event.target;
      if (!(target instanceof Element)) {
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
      // Model menu takes priority over slash command menu
      if (showModelMenu) {
        // Defensive guard against race conditions where filteredModels could empty
        if (filteredModels.length === 0) {
          return;
        }

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setModelSelectedIndex((previous) => (previous + 1) % filteredModels.length);
          return;
        }

        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setModelSelectedIndex(
            (previous) => (previous - 1 + filteredModels.length) % filteredModels.length,
          );
          return;
        }

        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          const safeIndex = Math.min(modelSelectedIndex, filteredModels.length - 1);
          if (safeIndex >= 0) {
            handleSelectModel(filteredModels[safeIndex]);
          }
          return;
        }

        if (e.key === 'Escape') {
          e.preventDefault();
          if (detectedModelTriggerKey) {
            setDismissedModelTriggerKey(detectedModelTriggerKey);
          }
          return;
        }
      }

      if (showFileMenu) {
        if (pickerEntries.length === 0) {
          if (e.key === 'Escape') {
            e.preventDefault();
            if (detectedFileTriggerKey) {
              setDismissedFileTriggerKey(detectedFileTriggerKey);
            }
          }
          return;
        }

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setFileSelectedIndex((previous) => (previous + 1) % pickerEntries.length);
          return;
        }

        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setFileSelectedIndex((previous) => (previous - 1 + pickerEntries.length) % pickerEntries.length);
          return;
        }

        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          const safeIndex = Math.min(fileSelectedIndex, pickerEntries.length - 1);
          if (safeIndex >= 0) {
            handleSelectFile(pickerEntries[safeIndex]);
          }
          return;
        }

        if (e.key === 'Escape') {
          e.preventDefault();
          if (detectedFileTriggerKey) {
            setDismissedFileTriggerKey(detectedFileTriggerKey);
          }
          return;
        }
      }

      if (showSlashMenu) {
        // Defensive guard against race conditions
        if (filteredSkills.length === 0) {
          return;
        }

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
          const safeIndex = Math.min(selectedIndex, filteredSkills.length - 1);
          if (safeIndex >= 0) {
            handleSelectCommand(filteredSkills[safeIndex]);
          }
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
        {showSlashMenu && (
          <Suspense fallback={null}>
            <SlashCommandMenu
              skills={filteredSkills}
              selectedIndex={selectedIndex}
              position={menuPosition}
              onSelect={handleSelectCommand}
              onHover={setSelectedIndex}
            />
          </Suspense>
        )}

        {showModelMenu && (
          <Suspense fallback={null}>
            <ModelCommandMenu
              models={filteredModels}
              selectedIndex={modelSelectedIndex}
              position={modelMenuPosition}
              onSelect={handleSelectModel}
              onHover={setModelSelectedIndex}
            />
          </Suspense>
        )}

        {showFileMenu && activeFileTrigger && (
          <Suspense fallback={null}>
            <FilePickerMenu
              searchQuery={activeFileTrigger.searchTerm}
              selectedIndex={fileSelectedIndex}
              position={fileMenuPosition}
              onSelect={handleSelectFile}
              onClose={() => {
                if (detectedFileTriggerKey) {
                  setDismissedFileTriggerKey(detectedFileTriggerKey);
                }
              }}
              onSelectedIndexChange={setFileSelectedIndex}
              onEntriesChange={handleFileEntriesChange}
            />
          </Suspense>
        )}

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
              setDismissedModelTriggerKey(null);
              setDismissedFileTriggerKey(null);
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
