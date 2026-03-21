import { describe, expect, test, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { InlineYouTubeApprovalBlock } from '../../../components/chat/InlineYouTubeApprovalBlock';
import type { YouTubeTranscriptionApprovalBlock } from '../../../types';

function makeApproval(
  overrides: Partial<YouTubeTranscriptionApprovalBlock> = {},
): YouTubeTranscriptionApprovalBlock {
  return {
    requestId: 'req-1',
    title: 'Test Video',
    channel: 'Test Channel',
    duration: '12:34',
    url: 'https://youtube.com/watch?v=abc',
    noCaptionsReason: 'No captions available',
    audioSizeEstimate: '15 MB',
    downloadTimeEstimate: '10s',
    transcriptionTimeEstimate: '30s',
    totalTimeEstimate: '40s',
    whisperModel: 'small',
    computeBackend: 'cpu',
    status: 'pending',
    ...overrides,
  };
}

describe('InlineYouTubeApprovalBlock', () => {
  test('renders key metadata fields and link', () => {
    render(<InlineYouTubeApprovalBlock approval={makeApproval()} />);

    expect(screen.getByText('Fallback transcription approval')).toBeInTheDocument();
    expect(screen.getByText('Estimated total time')).toBeInTheDocument();
    expect(screen.getByText('40s')).toBeInTheDocument();
    expect(screen.getByText(/Title:/)).toBeInTheDocument();
    expect(screen.getByText('Test Video')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'https://youtube.com/watch?v=abc' })).toBeInTheDocument();
  });

  test('renders playlist note when provided', () => {
    render(
      <InlineYouTubeApprovalBlock
        approval={makeApproval({ playlistNote: 'Only first item will be processed.' })}
      />,
    );

    expect(screen.getByText('Only first item will be processed.')).toBeInTheDocument();
  });

  test('calls onRespond for deny and allow actions in pending status', () => {
    const onRespond = vi.fn();
    render(
      <InlineYouTubeApprovalBlock
        approval={makeApproval({ requestId: 'req-42', status: 'pending' })}
        onRespond={onRespond}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Deny' }));
    fireEvent.click(screen.getByRole('button', { name: 'Allow' }));

    expect(onRespond).toHaveBeenNthCalledWith(1, 'req-42', false);
    expect(onRespond).toHaveBeenNthCalledWith(2, 'req-42', true);
  });

  test('hides action buttons when no responder is provided', () => {
    render(
      <InlineYouTubeApprovalBlock approval={makeApproval({ status: 'pending' })} />,
    );

    expect(screen.queryByRole('button', { name: 'Deny' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Allow' })).not.toBeInTheDocument();
  });

  test('shows approved status copy', () => {
    render(
      <InlineYouTubeApprovalBlock approval={makeApproval({ status: 'approved' })} />,
    );

    expect(screen.getByText('Approved. Starting transcription...')).toBeInTheDocument();
  });

  test('shows denied status copy', () => {
    render(
      <InlineYouTubeApprovalBlock approval={makeApproval({ status: 'denied' })} />,
    );

    expect(
      screen.getByText('Denied. Transcription fallback was not run.'),
    ).toBeInTheDocument();
  });
});
