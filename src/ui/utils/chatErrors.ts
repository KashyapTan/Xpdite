import type {
  ChatErrorAction,
  ChatErrorSource,
  ChatMessage,
} from '../types';
import { getModelProviderKey, getProviderLabel } from './modelDisplay';

export interface ChatErrorDescriptor {
  message: ChatMessage;
  rawError: string;
  status: string;
}

interface DescribeChatErrorOptions {
  rawError: string;
  source: ChatErrorSource;
  action?: ChatErrorAction;
  model?: string;
}

interface DescribeChatErrorResult {
  title: string;
  status: string;
  summary: string;
  nextStep?: string;
}

interface CreateChatErrorMessageOptions extends DescribeChatErrorOptions {
  model?: string;
  timestamp?: number;
}

function normalizeRawError(rawError: string): string {
  return rawError.replace(/\s+/g, ' ').trim();
}

function includesEvery(haystack: string, needles: string[]): boolean {
  return needles.every((needle) => haystack.includes(needle));
}

function hasAny(haystack: string, needles: string[]): boolean {
  return needles.some((needle) => haystack.includes(needle));
}

function extractMissingApiKeyProvider(rawError: string): string | null {
  const explicitMatch = rawError.match(/no api key configured for ([a-z0-9_-]+)/i);
  if (explicitMatch?.[1]) {
    return explicitMatch[1].toLowerCase();
  }

  const legacyMatch = rawError.match(/no api key for ([a-z0-9_-]+)/i);
  if (legacyMatch?.[1]) {
    return legacyMatch[1].toLowerCase();
  }

  return null;
}

function describeChatError({
  rawError,
  source,
  action = 'unknown',
  model,
}: DescribeChatErrorOptions): DescribeChatErrorResult {
  const lowerRaw = rawError.toLowerCase();
  const providerKey = model ? getModelProviderKey(model) : null;
  const providerLabel = providerKey ? getProviderLabel(providerKey) : null;
  const missingApiKeyProvider = extractMissingApiKeyProvider(rawError);
  const missingApiKeyProviderLabel = missingApiKeyProvider
    ? getProviderLabel(missingApiKeyProvider)
    : null;
  const usesOllama = providerKey === 'ollama'
    || lowerRaw.includes('ollama')
    || lowerRaw.includes('localhost:11434');
  const connectionFailurePatterns = [
    'all connection attempts failed',
    'cannot connect to ollama',
    'connection refused',
    'actively refused',
    'failed to connect',
    'unable to connect',
    'connecterror',
    'max retries exceeded',
    'winerror 10061',
    'localhost:11434',
  ];
  const isLikelyConnectionFailure = hasAny(lowerRaw, connectionFailurePatterns);

  if (source === 'connection') {
    return {
      title: 'Backend disconnected',
      status: 'Connection lost. Retrying...',
      summary: 'I lost the connection to the local Xpdite backend before this chat could finish.',
      nextStep: 'The app is retrying automatically. If the request does not resume after reconnecting, send it again.',
    };
  }

  if (source === 'client') {
    return {
      title: 'Chat UI failed to apply an update',
      status: 'Chat UI error.',
      summary: 'The frontend hit an unexpected error while routing or rendering a chat event.',
      nextStep: 'The backend may still be fine, but this conversation state may be out of sync until the next successful update.',
    };
  }

  if (source === 'queue' || lowerRaw.includes('queue is full')) {
    return {
      title: 'Queue full',
      status: 'Queue full.',
      summary: 'This tab already has the maximum number of queued chat requests.',
      nextStep: 'Let one finish or cancel a queued item, then try again.',
    };
  }

  if (lowerRaw.startsWith('queued message failed:')) {
    return {
      title: 'Queued request failed',
      status: 'Queued request failed.',
      summary: 'A queued request failed before it finished processing.',
      nextStep: 'Later queued items can still continue, but this request needs to be retried manually.',
    };
  }

  if (missingApiKeyProviderLabel) {
    return {
      title: `${missingApiKeyProviderLabel} API key missing`,
      status: 'Provider setup required.',
      summary: `This chat model needs a valid ${missingApiKeyProviderLabel} API key before it can answer.`,
      nextStep: `Open Settings, add the ${missingApiKeyProviderLabel} key, and retry this message.`,
    };
  }

  if (includesEvery(lowerRaw, ['llm service', 'temporarily unavailable'])) {
    if (usesOllama) {
      return {
        title: 'Ollama request failed',
        status: 'Ollama request failed.',
        summary: 'The local Ollama runtime could not produce a usable response for this chat request.',
        nextStep: 'Confirm Ollama is running and retry. If it keeps failing, switch to a different model.',
      };
    }

    return {
      title: providerLabel ? `${providerLabel} request failed` : 'LLM service unavailable',
      status: providerLabel ? `${providerLabel} request failed.` : 'LLM service unavailable.',
      summary: providerLabel
        ? `The ${providerLabel} provider did not return a usable response for this chat request.`
        : 'The selected model provider did not return a usable response.',
      nextStep: 'This is usually temporary. Try again in a moment or switch to another model.',
    };
  }

  if (lowerRaw.includes('already streaming')) {
    return {
      title: 'Another response is already running',
      status: 'Another response is already running.',
      summary: 'This tab already has an active response in progress, so I could not start a second one.',
      nextStep: 'Wait for the current response to finish or stop it first.',
    };
  }

  if (lowerRaw.includes('retry/edit actions require a target message') || lowerRaw.includes('missing message_id')) {
    return {
      title: action === 'edit' ? 'Edit target missing' : 'Retry target missing',
      status: action === 'edit' ? 'Edit failed.' : 'Retry failed.',
      summary: 'The app could not locate the saved message needed for that action.',
      nextStep: 'Reload the conversation and try again once the target message is persisted.',
    };
  }

  if (lowerRaw.includes('selected message could not be found')) {
    return {
      title: 'Message not found',
      status: 'Message not found.',
      summary: 'The saved message for this chat action no longer exists in the conversation store.',
      nextStep: 'Reload the conversation and try again.',
    };
  }

  if (lowerRaw.includes('selected turn is incomplete') || lowerRaw.includes('does not have an assistant response yet')) {
    return {
      title: 'Turn cannot be regenerated',
      status: 'Turn cannot be regenerated.',
      summary: 'That conversation turn does not have the full saved state needed for retry or edit.',
      nextStep: 'Pick a completed turn and try again.',
    };
  }

  if (lowerRaw.includes('selected turn does not have a user message')) {
    return {
      title: 'Turn cannot be edited',
      status: 'Edit failed.',
      summary: 'That saved conversation turn is missing its original user message, so it cannot be edited safely.',
      nextStep: 'Reload the conversation and edit a complete saved turn instead.',
    };
  }

  if (lowerRaw.includes('only user messages can be edited')) {
    return {
      title: 'Only user messages can be edited',
      status: 'Edit failed.',
      summary: 'The edit action was sent for a non-user message.',
      nextStep: 'Edit the original user prompt instead of the assistant response.',
    };
  }

  if (lowerRaw.includes('selected turn could not be updated')) {
    return {
      title: 'Edited turn could not be saved',
      status: 'Edit failed.',
      summary: 'The saved conversation turn changed before the edit could be applied.',
      nextStep: 'Reload the conversation and try the edit again.',
    };
  }

  if (
    lowerRaw.includes('invalid response_index')
    || lowerRaw.includes('missing or invalid active response selection')
    || lowerRaw.includes('assistant message not found')
    || lowerRaw.includes('requested response variant does not exist')
    || lowerRaw.includes('only assistant responses can switch variants')
  ) {
    return {
      title: 'Saved response not available',
      status: 'Response switch failed.',
      summary: 'The selected saved response variant could not be found or applied.',
      nextStep: 'Reload the conversation and try switching responses again.',
    };
  }

  if (lowerRaw.includes('blocked by claude-compatible hook') || lowerRaw.includes('blocked by')) {
    return {
      title: 'Request blocked by hook',
      status: 'Request blocked.',
      summary: 'A configured workflow hook prevented this prompt from running.',
      nextStep: 'Review the hook output or configuration, then retry the request.',
    };
  }

  if (lowerRaw.includes('empty query')) {
    return {
      title: 'Message was empty',
      status: 'Message was empty.',
      summary: 'The backend rejected this request because it did not contain any prompt text.',
      nextStep: 'Enter a message and try again.',
    };
  }

  if (usesOllama && isLikelyConnectionFailure) {
    return {
      title: 'Ollama is not running',
      status: 'Ollama is not reachable.',
      summary: 'This chat model depends on the local Ollama service, but Xpdite could not reach Ollama on http://localhost:11434.',
      nextStep: 'Launch Ollama, wait for it to finish starting, and retry this message.',
    };
  }

  if (isLikelyConnectionFailure) {
    return {
      title: providerLabel ? `${providerLabel} endpoint is unreachable` : 'Model service is unreachable',
      status: providerLabel ? `${providerLabel} endpoint is unreachable.` : 'Model service is unreachable.',
      summary: providerLabel
        ? `Xpdite could not connect to the ${providerLabel} endpoint for this chat request.`
        : 'Xpdite could not connect to the model service for this chat request.',
      nextStep: 'Check your network or provider configuration, then retry.',
    };
  }

  if (
    usesOllama
    && (
      hasAny(lowerRaw, ['try pulling it first', 'pull model manifest', 'manifest unknown', 'model not found'])
      || (lowerRaw.includes('not found') && lowerRaw.includes('model'))
    )
  ) {
    return {
      title: 'Ollama model is missing',
      status: 'Model not available in Ollama.',
      summary: 'The selected model is not installed in the local Ollama runtime.',
      nextStep: 'Pull the model in Settings or Ollama, then retry this message.',
    };
  }

  if (hasAny(lowerRaw, ['timed out', 'timeout'])) {
    return {
      title: usesOllama
        ? 'Ollama request timed out'
        : providerLabel
          ? `${providerLabel} request timed out`
          : 'Model request timed out',
      status: 'Request timed out.',
      summary: usesOllama
        ? 'The local model did not finish responding before this request timed out.'
        : providerLabel
          ? `The ${providerLabel} provider did not respond before this request timed out.`
          : 'The selected model did not respond before this request timed out.',
      nextStep: usesOllama
        ? 'Retry, or switch to a smaller or faster model if this keeps happening.'
        : 'Retry in a moment, or switch models if it keeps happening.',
    };
  }

  if (usesOllama && lowerRaw.startsWith('llm api error')) {
    return {
      title: 'Ollama request failed',
      status: 'Ollama request failed.',
      summary: 'The local Ollama runtime returned an API error while generating this reply.',
      nextStep: 'Retry the request. If it keeps failing, restart Ollama or switch models.',
    };
  }

  if (
    lowerRaw.includes('internal error processing request')
    || lowerRaw.includes('error processing request')
    || lowerRaw.includes('unsupported conversation action')
  ) {
    return {
      title: 'Request processing failed',
      status: 'Request processing failed.',
      summary: 'The backend hit an internal error while handling this chat request.',
      nextStep: 'If this keeps happening, check the server logs and try again.',
    };
  }

  if (action === 'retry') {
    return {
      title: 'Retry failed',
      status: 'Retry failed.',
      summary: 'I could not regenerate that saved response.',
      nextStep: 'Try again after reloading the conversation or switch to a different model.',
    };
  }

  if (action === 'edit') {
    return {
      title: 'Edit failed',
      status: 'Edit failed.',
      summary: 'I could not resubmit the edited prompt for this conversation turn.',
      nextStep: 'Try saving the edit again after the conversation finishes syncing.',
    };
  }

  if (action === 'response_variant') {
    return {
      title: 'Response switch failed',
      status: 'Response switch failed.',
      summary: 'I could not switch to the selected saved assistant response.',
      nextStep: 'Reload the conversation and try again.',
    };
  }

  return {
    title: 'Chat request failed',
    status: 'Chat request failed.',
    summary: 'I could not complete that chat action because the app returned an error.',
    nextStep: 'Try again once the backend is ready.',
  };
}

function buildMessageBody(description: DescribeChatErrorResult, rawError: string): string {
  const sections = [description.summary];
  const lowerSummary = description.summary.toLowerCase();
  const lowerNextStep = description.nextStep?.toLowerCase() ?? '';
  const lowerRaw = rawError.toLowerCase();

  if (
    rawError
    && !lowerSummary.includes(lowerRaw)
    && !lowerNextStep.includes(lowerRaw)
  ) {
    sections.push(`Detail: ${rawError}`);
  }

  if (description.nextStep) {
    sections.push(description.nextStep);
  }

  return `**${description.title}**\n\n${sections.join('\n\n')}`;
}

export function createChatErrorMessage({
  rawError,
  source,
  action = 'unknown',
  model,
  timestamp = Date.now(),
}: CreateChatErrorMessageOptions): ChatMessage {
  const normalizedRawError = normalizeRawError(rawError) || 'Unknown chat error.';
  const description = describeChatError({
    rawError: normalizedRawError,
    source,
    action,
    model,
  });

  return {
    role: 'assistant',
    content: buildMessageBody(description, normalizedRawError),
    model,
    timestamp,
    variant: 'error',
    errorContext: {
      source,
      action,
      rawMessage: normalizedRawError,
    },
  };
}

export function createChatErrorDescriptor(
  options: CreateChatErrorMessageOptions,
): ChatErrorDescriptor {
  const normalizedRawError = normalizeRawError(options.rawError) || 'Unknown chat error.';
  const description = describeChatError({
    rawError: normalizedRawError,
    source: options.source,
    action: options.action,
    model: options.model,
  });

  return {
    message: createChatErrorMessage({
      ...options,
      rawError: normalizedRawError,
    }),
    rawError: normalizedRawError,
    status: description.status,
  };
}
