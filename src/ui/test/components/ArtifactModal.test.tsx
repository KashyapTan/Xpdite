import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { ArtifactModal } from '../../components/ArtifactModal';
import { api } from '../../services/api';
import type { ArtifactBlockData } from '../../types';

vi.mock('../../services/api', () => ({
  api: {
    getArtifact: vi.fn(),
    updateArtifact: vi.fn(),
    deleteArtifact: vi.fn(),
  },
}));

vi.mock('../../utils/clipboard', () => ({
  copyToClipboard: vi.fn(),
}));

const baseArtifact: ArtifactBlockData = {
  artifactId: 'artifact-1',
  artifactType: 'html',
  title: 'demo.html',
  sizeBytes: 12,
  lineCount: 1,
  status: 'ready',
  content: '<h1>Hello</h1>',
};

describe('ArtifactModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  test('renders HTML preview iframe without script permissions', () => {
    render(
      <ArtifactModal
        artifact={baseArtifact}
        onClose={vi.fn()}
      />,
    );

    const iframe = screen.getByTitle('demo.html');
    expect(iframe).toHaveAttribute('sandbox', '');
    expect(iframe).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  test('emits updated artifact payload after saving edits', async () => {
    const onUpdated = vi.fn();
    vi.mocked(api.updateArtifact).mockResolvedValue({
      id: 'artifact-1',
      type: 'html',
      title: 'updated.html',
      content: '<h1>Updated</h1>',
      sizeBytes: 16,
      lineCount: 1,
      status: 'ready',
    });

    render(
      <ArtifactModal
        artifact={baseArtifact}
        onClose={vi.fn()}
        onUpdated={onUpdated}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Edit artifact' }));
    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'updated.html' },
    });
    fireEvent.change(screen.getByLabelText('Content'), {
      target: { value: '<h1>Updated</h1>' },
    });
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(api.updateArtifact).toHaveBeenCalledWith('artifact-1', {
        title: 'updated.html',
        content: '<h1>Updated</h1>',
        language: undefined,
      });
    });

    expect(onUpdated).toHaveBeenCalledWith(
      expect.objectContaining({
        artifactId: 'artifact-1',
        title: 'updated.html',
        content: '<h1>Updated</h1>',
      }),
    );
  });

  test('emits deleted artifact id and closes after deletion', async () => {
    const onDeleted = vi.fn();
    const onClose = vi.fn();
    vi.mocked(api.deleteArtifact).mockResolvedValue(undefined);

    render(
      <ArtifactModal
        artifact={baseArtifact}
        onClose={onClose}
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Delete artifact' }));

    await waitFor(() => {
      expect(api.deleteArtifact).toHaveBeenCalledWith('artifact-1');
    });

    expect(onDeleted).toHaveBeenCalledWith('artifact-1');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
