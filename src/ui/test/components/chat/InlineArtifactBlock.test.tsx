import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import { InlineArtifactBlock } from '../../../components/chat/InlineArtifactBlock';
import type { ArtifactBlockData } from '../../../types';

vi.mock('../../../components/ArtifactModal', () => ({
  ArtifactModal: ({ artifact }: { artifact: { title: string } }) => (
    <div>artifact-modal:{artifact.title}</div>
  ),
}));

describe('InlineArtifactBlock', () => {
  test('renders live streamed artifact content inside the inline card', () => {
    const artifact: ArtifactBlockData = {
      artifactId: 'artifact-1',
      artifactType: 'code',
      title: 'demo.py',
      language: 'python',
      sizeBytes: 0,
      lineCount: 0,
      status: 'streaming',
      content: 'print("hi")',
    };

    render(<InlineArtifactBlock artifact={artifact} />);

    expect(screen.getByText('demo.py')).toBeInTheDocument();
    expect(screen.getByText('Live content')).toBeInTheDocument();
    expect(screen.getByText('print("hi")')).toBeInTheDocument();
    expect(screen.getByText('11 B')).toBeInTheDocument();
    expect(screen.getByText('1 lines')).toBeInTheDocument();
    expect(screen.queryByText('Artifact content is opening. Live output will appear here as soon as the model emits it.')).not.toBeInTheDocument();
  });

  test('opens the artifact modal for ready artifacts', () => {
    const artifact: ArtifactBlockData = {
      artifactId: 'artifact-2',
      artifactType: 'markdown',
      title: 'notes.md',
      sizeBytes: 18,
      lineCount: 2,
      status: 'ready',
      content: '# Notes\nReady',
    };

    render(<InlineArtifactBlock artifact={artifact} />);

    fireEvent.click(screen.getByRole('button', { name: /notes\.md/i }));

    expect(screen.getByText('artifact-modal:notes.md')).toBeInTheDocument();
  });
});
