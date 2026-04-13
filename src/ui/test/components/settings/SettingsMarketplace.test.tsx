import { beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsMarketplace from '../../../components/settings/SettingsMarketplace';
import { api } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  api: {
    getMarketplaceSources: vi.fn(),
    getMarketplaceCatalog: vi.fn(),
    getMarketplaceInstalls: vi.fn(),
    createMarketplaceSource: vi.fn(),
    deleteMarketplaceSource: vi.fn(),
    refreshMarketplaceSource: vi.fn(),
    installMarketplaceItem: vi.fn(),
    installMarketplacePackage: vi.fn(),
    installMarketplaceRepo: vi.fn(),
    setMarketplaceInstallEnabled: vi.fn(),
    updateMarketplaceInstall: vi.fn(),
    deleteMarketplaceInstall: vi.fn(),
    updateMarketplaceSecrets: vi.fn(),
  },
}));

const mockedApi = vi.mocked(api);

describe('SettingsMarketplace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getMarketplaceSources.mockResolvedValue([
      {
        id: 'builtin-claude-skills',
        name: 'Anthropic Skills',
        kind: 'remote_manifest',
        location: 'https://example.com/skills.json',
        enabled: true,
        builtin: true,
        manifest: null,
        last_sync_at: null,
        last_error: null,
      },
    ]);
    mockedApi.getMarketplaceCatalog.mockResolvedValue([
      {
        source_id: 'builtin-claude-skills',
        manifest_item_id: 'planner-skill',
        kind: 'plugin',
        display_name: 'Planner Skill',
        description: 'Standalone native skill',
        required_secrets: [],
        component_counts: { skills: 1, mcp_servers: 0 },
        compatibility_warnings: [],
        raw: {},
        install: null,
      },
    ]);
    mockedApi.getMarketplaceInstalls.mockResolvedValue([]);
    mockedApi.createMarketplaceSource.mockResolvedValue({
      id: 'user-source',
      name: 'Custom',
      kind: 'local_manifest',
      location: '/tmp/marketplace.json',
      enabled: true,
      builtin: false,
      manifest: null,
      last_sync_at: null,
      last_error: null,
    });
    mockedApi.installMarketplaceItem.mockResolvedValue({
      id: 'install-1',
      item_kind: 'skill',
      source_id: 'builtin-claude-skills',
      manifest_item_id: 'planner-skill',
      display_name: 'Planner Skill',
      canonical_id: 'planner:triage',
      install_root: '/tmp/install-1',
      status: 'installed',
      enabled: true,
      required_secrets: [],
    });
    mockedApi.installMarketplacePackage.mockResolvedValue({
      id: 'install-package-1',
      item_kind: 'mcp',
      source_id: null,
      manifest_item_id: 'server-everything',
      display_name: '@modelcontextprotocol/server-everything',
      install_root: '/tmp/install-package-1',
      status: 'connected',
      enabled: true,
      required_secrets: [],
    });
  });

  test('loads sources and catalog', async () => {
    render(<SettingsMarketplace />);

    expect(await screen.findByText('Anthropic Skills')).toBeInTheDocument();
    expect(screen.getByText('Planner Skill')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Install' })).toBeInTheDocument();
  });

  test('adds a custom source', async () => {
    render(<SettingsMarketplace />);

    fireEvent.change(screen.getByPlaceholderText('Source name'), { target: { value: 'Custom' } });
    fireEvent.change(screen.getByPlaceholderText('Manifest URL or local path'), { target: { value: '/tmp/marketplace.json' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add Source' }));

    await waitFor(() => {
      expect(mockedApi.createMarketplaceSource).toHaveBeenCalledWith({
        name: 'Custom',
        location: '/tmp/marketplace.json',
      });
    });
  });

  test('installs a direct npx package', async () => {
    render(<SettingsMarketplace />);

    fireEvent.change(screen.getByPlaceholderText(/Package\/args/i), {
      target: { value: '@modelcontextprotocol/server-everything --debug' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Install Package' }));

    await waitFor(() => {
      expect(mockedApi.installMarketplacePackage).toHaveBeenCalledWith({
        runner: 'npx',
        package_input: '@modelcontextprotocol/server-everything --debug',
      });
    });
  });

  test('installs a direct Claude repo', async () => {
    mockedApi.installMarketplaceRepo.mockResolvedValue({
      id: 'install-repo-1',
      item_kind: 'plugin',
      source_id: null,
      manifest_item_id: 'caveman',
      display_name: 'caveman',
      install_root: '/tmp/install-repo-1',
      status: 'installed',
      enabled: true,
      required_secrets: [],
    });

    render(<SettingsMarketplace />);

    fireEvent.change(screen.getByPlaceholderText(/GitHub repo, URL, or local path/i), {
      target: { value: 'JuliusBrussee/caveman' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Install Repo' }));

    await waitFor(() => {
      expect(mockedApi.installMarketplaceRepo).toHaveBeenCalledWith({
        repo_input: 'JuliusBrussee/caveman',
      });
    });
  });

  test('installs a catalog item', async () => {
    render(<SettingsMarketplace />);

    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));

    await waitFor(() => {
      expect(mockedApi.installMarketplaceItem).toHaveBeenCalledWith({
        source_id: 'builtin-claude-skills',
        manifest_item_id: 'planner-skill',
        secrets: {},
      });
    });
  });

  test('catalog search keeps matching items visible in the single combined list', async () => {
    render(<SettingsMarketplace />);

    fireEvent.change(await screen.findByPlaceholderText('Search catalog'), {
      target: { value: 'Planner' },
    });

    expect(await screen.findByText('Planner Skill')).toBeInTheDocument();
  });
});
