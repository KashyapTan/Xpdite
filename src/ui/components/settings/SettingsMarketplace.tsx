import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RotateCcwIcon, TrashIcon } from '../icons/AppIcons';
import { api } from '../../services/api';
import type {
  MarketplaceCatalogItem,
  MarketplaceInstall,
  MarketplaceSource,
} from '../../services/api';
import '../../CSS/settings/SettingsMarketplace.css';

type PackageRunner = 'npx' | 'uvx';
type SecretModalState = {
  title: string;
  subtitle: string;
  secretNames: string[];
};

function labelForKind(kind: MarketplaceCatalogItem['kind'] | MarketplaceInstall['item_kind']): string {
  if (kind === 'mcp') return 'MCP';
  if (kind === 'plugin') return 'Plugin';
  return 'Skill';
}

function sourceSubtitle(source: MarketplaceSource): string {
  if (source.id === 'builtin-claude-plugins' || source.id === 'builtin-claude-skills') {
    return 'Official Anthropic catalog';
  }
  if (source.id === 'builtin-mcp-registry') {
    return 'Official/verified MCP Registry entries';
  }
  if (source.builtin) {
    return 'Built-in curated source';
  }
  return 'Custom source';
}

function getInstallCounts(install: MarketplaceInstall): { skills: number; commands: number; mcpServers: number } {
  const componentManifest = (install.component_manifest ?? {}) as {
    skills?: unknown[];
    commands?: unknown[];
    mcp_manifests?: unknown[];
    mcp_manifest?: unknown;
  };

  const skills = Array.isArray(componentManifest.skills) ? componentManifest.skills.length : 0;
  const commands = Array.isArray(componentManifest.commands) ? componentManifest.commands.length : 0;
  const mcpServers = Array.isArray(componentManifest.mcp_manifests)
    ? componentManifest.mcp_manifests.length
    : componentManifest.mcp_manifest
      ? 1
      : 0;

  return { skills, commands, mcpServers };
}

function getInstallSlashCommands(install: MarketplaceInstall): string[] {
  const componentManifest = (install.component_manifest ?? {}) as {
    plugin_manifest?: { name?: string };
    skills?: Array<{ slash_command?: string; name?: string; metadata?: { slash_command?: string; command?: string; name?: string } }>;
    commands?: Array<{ slash_command?: string; name?: string; metadata?: { slash_command?: string; command?: string; name?: string } }>;
  };

  if (install.item_kind === 'skill') {
    return install.canonical_id ? [install.canonical_id] : [];
  }

  const pluginId = install.canonical_id
    || componentManifest.plugin_manifest?.name
    || install.display_name;
  const commands = new Set<string>();

  for (const item of componentManifest.skills ?? []) {
    const localCommand = item.slash_command
      || item.metadata?.slash_command
      || item.metadata?.command
      || item.name
      || item.metadata?.name;
    if (!localCommand) {
      continue;
    }
    commands.add(localCommand.includes(':') ? localCommand : `${pluginId}:${localCommand}`);
  }

  for (const item of componentManifest.commands ?? []) {
    const command = item.slash_command
      || item.metadata?.slash_command
      || item.metadata?.command
      || item.name
      || item.metadata?.name;
    if (command) {
      commands.add(command);
    }
  }

  return Array.from(commands).sort();
}

function getInstallOriginLabel(install: MarketplaceInstall): string | null {
  const rawKind = String((install.raw_source ?? {}).kind ?? '');
  if (rawKind === 'direct_repo') {
    return 'Direct repo install';
  }
  if (rawKind === 'direct_package') {
    return 'Direct package install';
  }
  return null;
}

function getInstallWarnings(install: MarketplaceInstall): string[] {
  const componentManifest = (install.component_manifest ?? {}) as {
    compatibility_warnings?: unknown;
  };
  return Array.isArray(componentManifest.compatibility_warnings)
    ? componentManifest.compatibility_warnings.filter((warning): warning is string => typeof warning === 'string' && warning.trim().length > 0)
    : [];
}

function getInstallAuthInstructions(install: MarketplaceInstall): string {
  const rawSource = (install.raw_source ?? {}) as { auth_instructions?: unknown };
  if (typeof rawSource.auth_instructions === 'string' && rawSource.auth_instructions.trim()) {
    return rawSource.auth_instructions;
  }
  return 'Enter the required secret values to finish configuring this integration.';
}

const SettingsMarketplace: React.FC = () => {
  const [sources, setSources] = useState<MarketplaceSource[]>([]);
  const [catalog, setCatalog] = useState<MarketplaceCatalogItem[]>([]);
  const [installs, setInstalls] = useState<MarketplaceInstall[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogVisibleCount, setCatalogVisibleCount] = useState(100);
  const [sourceName, setSourceName] = useState('');
  const [sourceLocation, setSourceLocation] = useState('');
  const [repoInput, setRepoInput] = useState('');
  const [packageRunner, setPackageRunner] = useState<PackageRunner>('npx');
  const [packageInput, setPackageInput] = useState('');
  const [secretModal, setSecretModal] = useState<SecretModalState | null>(null);
  const [secretValues, setSecretValues] = useState<Record<string, string>>({});
  const [secretError, setSecretError] = useState('');
  const secretResolverRef = useRef<((value: Record<string, string> | null) => void) | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSources, nextCatalog, nextInstalls] = await Promise.all([
        api.getMarketplaceSources(),
        api.getMarketplaceCatalog(),
        api.getMarketplaceInstalls(),
      ]);
      setSources(nextSources);
      setCatalog(nextCatalog);
      setInstalls(nextInstalls);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load marketplace');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const filteredCatalog = useMemo(() => {
    const query = catalogQuery.trim().toLowerCase();
    return catalog.filter((item) => {
      if (!query) {
        return true;
      }
      const haystack = `${item.display_name} ${item.description}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [catalog, catalogQuery]);

  const visibleCatalog = useMemo(
    () => filteredCatalog.slice(0, catalogVisibleCount),
    [catalogVisibleCount, filteredCatalog],
  );

  useEffect(() => {
    setCatalogVisibleCount(100);
  }, [catalogQuery]);

  const requestSecrets = useCallback((
    secretNames: string[],
    title: string,
    subtitle: string,
  ): Promise<Record<string, string> | null> => new Promise((resolve) => {
    secretResolverRef.current = resolve;
    setSecretValues(
      Object.fromEntries(secretNames.map((secretName) => [secretName, ''])),
    );
    setSecretError('');
    setSecretModal({ title, subtitle, secretNames });
  }), []);

  const closeSecretModal = useCallback(() => {
    if (secretResolverRef.current) {
      secretResolverRef.current(null);
      secretResolverRef.current = null;
    }
    setSecretModal(null);
    setSecretValues({});
    setSecretError('');
  }, []);

  const submitSecretModal = useCallback(() => {
    if (!secretModal || !secretResolverRef.current) {
      return;
    }

    const secrets: Record<string, string> = {};
    for (const secretName of secretModal.secretNames) {
      const value = (secretValues[secretName] ?? '').trim();
      if (!value) {
        setSecretError(`A value is required for ${secretName}.`);
        return;
      }
      secrets[secretName] = value;
    }

    const resolve = secretResolverRef.current;
    secretResolverRef.current = null;
    setSecretModal(null);
    setSecretValues({});
    setSecretError('');
    resolve(secrets);
  }, [secretModal, secretValues]);

  const handleCreateSource = useCallback(async () => {
    if (!sourceLocation.trim()) {
      setError('Marketplace source location is required');
      return;
    }
    setBusyKey('create-source');
    try {
      await api.createMarketplaceSource({
        name: sourceName.trim() || sourceLocation.trim(),
        location: sourceLocation.trim(),
      });
      setSourceName('');
      setSourceLocation('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add marketplace source');
    } finally {
      setBusyKey(null);
    }
  }, [refresh, sourceLocation, sourceName]);

  const handleInstallPackage = useCallback(async () => {
    if (!packageInput.trim()) {
      setError('Package command is required');
      return;
    }
    setBusyKey('install-package');
    try {
      const install = await api.installMarketplacePackage({
        runner: packageRunner,
        package_input: packageInput.trim(),
      });
      if (install.required_secrets && install.required_secrets.length > 0) {
        const secrets = await requestSecrets(
          install.required_secrets,
          `Configure ${install.display_name}`,
          getInstallAuthInstructions(install),
        );
        if (secrets && Object.keys(secrets).length > 0) {
          await api.updateMarketplaceSecrets(install.id, secrets);
          await api.setMarketplaceInstallEnabled(install.id, true);
        }
      }
      setPackageInput('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to install MCP package');
    } finally {
      setBusyKey(null);
    }
  }, [packageInput, packageRunner, refresh, requestSecrets]);

  const handleInstallRepo = useCallback(async () => {
    if (!repoInput.trim()) {
      setError('Repository input is required');
      return;
    }
    setBusyKey('install-repo');
    try {
      const install = await api.installMarketplaceRepo({
        repo_input: repoInput.trim(),
      });
      if (install.required_secrets && install.required_secrets.length > 0) {
        const secrets = await requestSecrets(
          install.required_secrets,
          `Configure ${install.display_name}`,
          getInstallAuthInstructions(install),
        );
        if (secrets && Object.keys(secrets).length > 0) {
          await api.updateMarketplaceSecrets(install.id, secrets);
          await api.setMarketplaceInstallEnabled(install.id, true);
        }
      }
      setRepoInput('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to install Claude repo');
    } finally {
      setBusyKey(null);
    }
  }, [refresh, repoInput, requestSecrets]);

  const handleRefreshSource = useCallback(async (sourceId: string) => {
    setBusyKey(`refresh-source:${sourceId}`);
    try {
      await api.refreshMarketplaceSource(sourceId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to refresh marketplace source');
    } finally {
      setBusyKey(null);
    }
  }, [refresh]);

  const handleDeleteSource = useCallback(async (sourceId: string) => {
    setBusyKey(`delete-source:${sourceId}`);
    try {
      await api.deleteMarketplaceSource(sourceId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete marketplace source');
    } finally {
      setBusyKey(null);
    }
  }, [refresh]);

  const handleInstall = useCallback(async (item: MarketplaceCatalogItem) => {
    setBusyKey(`install:${item.source_id}:${item.manifest_item_id}`);
    try {
      let secrets: Record<string, string> = {};
      if (item.required_secrets.length > 0) {
        const resolvedSecrets = await requestSecrets(
          item.required_secrets,
          `Install ${item.display_name}`,
          'Enter the required secret values to install this marketplace item.',
        );
        if (!resolvedSecrets || Object.keys(resolvedSecrets).length === 0) {
          setBusyKey(null);
          return;
        }
        secrets = resolvedSecrets;
      }
      await api.installMarketplaceItem({
        source_id: item.source_id,
        manifest_item_id: item.manifest_item_id,
        secrets,
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to install marketplace item');
    } finally {
      setBusyKey(null);
    }
  }, [refresh, requestSecrets]);

  const handleInstallSecrets = useCallback(async (install: MarketplaceInstall) => {
    const secretNames = install.required_secrets ?? [];
    if (secretNames.length === 0) {
      return;
    }
    setBusyKey(`secrets:${install.id}`);
    try {
      const secrets = await requestSecrets(
        secretNames,
        `Configure ${install.display_name}`,
        getInstallAuthInstructions(install),
      );
      if (!secrets || Object.keys(secrets).length === 0) {
        setBusyKey(null);
        return;
      }
      await api.updateMarketplaceSecrets(install.id, secrets);
      if (install.enabled) {
        await api.setMarketplaceInstallEnabled(install.id, true);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update marketplace secrets');
    } finally {
      setBusyKey(null);
    }
  }, [refresh, requestSecrets]);

  const handleSetEnabled = useCallback(async (installId: string, enabled: boolean) => {
    setBusyKey(`${enabled ? 'enable' : 'disable'}:${installId}`);
    try {
      await api.setMarketplaceInstallEnabled(installId, enabled);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update marketplace item');
    } finally {
      setBusyKey(null);
    }
  }, [refresh]);

  const handleUpdate = useCallback(async (installId: string) => {
    setBusyKey(`update:${installId}`);
    try {
      await api.updateMarketplaceInstall(installId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update marketplace item');
    } finally {
      setBusyKey(null);
    }
  }, [refresh]);

  const handleDeleteInstall = useCallback(async (installId: string) => {
    setBusyKey(`delete-install:${installId}`);
    try {
      await api.deleteMarketplaceInstall(installId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove marketplace item');
    } finally {
      setBusyKey(null);
    }
  }, [refresh]);

  return (
    <div className="settings-marketplace-container">
      <div className="settings-marketplace-header">
        <div>
          <h2>Marketplace</h2>
          <p>Install Claude-compatible skills, plugins, and MCP bundles from built-in or custom sources.</p>
        </div>
        <button
          className="settings-marketplace-refresh settings-marketplace-icon-button"
          onClick={() => void refresh()}
          disabled={loading}
          title={loading ? 'Refreshing marketplace' : 'Refresh marketplace'}
          aria-label={loading ? 'Refreshing marketplace' : 'Refresh marketplace'}
        >
          <RotateCcwIcon className={loading ? 'spin' : undefined} size={14} />
        </button>
      </div>

      {error && <div className="settings-marketplace-error">{error}</div>}

      <div className="settings-marketplace-scroll">
        <section className="settings-marketplace-panel">
          <div className="settings-marketplace-panel-header">
            <div>
              <h3>Sources</h3>
              <p>Built-in Claude-compatible catalogs are seeded automatically. Add raw marketplace URLs, GitHub repos, or local manifest files here.</p>
            </div>
          </div>
          <div className="settings-marketplace-source-form">
            <input
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
              placeholder="Source name"
            />
            <input
              value={sourceLocation}
              onChange={(event) => setSourceLocation(event.target.value)}
              placeholder="Marketplace URL, GitHub repo, or local manifest path"
            />
            <button onClick={() => void handleCreateSource()} disabled={busyKey === 'create-source'}>
              Add Source
            </button>
          </div>
          <div className="settings-marketplace-source-list">
            {sources.map((source) => (
              <div key={source.id} className="settings-marketplace-source-card" title={source.location}>
                <div className="settings-marketplace-source-copy">
                  <div className="settings-marketplace-source-row">
                    <div className="settings-marketplace-source-name">{source.name}</div>
                    <div className="settings-marketplace-source-meta">{sourceSubtitle(source)}</div>
                  </div>
                  {source.last_error && (
                    <div className="settings-marketplace-warning">{source.last_error}</div>
                  )}
                </div>
                <div className="settings-marketplace-actions">
                  <button
                    className="settings-marketplace-icon-button"
                    onClick={() => void handleRefreshSource(source.id)}
                    disabled={busyKey === `refresh-source:${source.id}`}
                    title={`Refresh ${source.name}`}
                    aria-label={`Refresh ${source.name}`}
                  >
                    <RotateCcwIcon className={busyKey === `refresh-source:${source.id}` ? 'spin' : undefined} size={14} />
                  </button>
                  {!source.builtin && (
                    <button
                      className="settings-marketplace-icon-button settings-marketplace-delete-button"
                      onClick={() => void handleDeleteSource(source.id)}
                      disabled={busyKey === `delete-source:${source.id}`}
                      title={`Remove ${source.name}`}
                      aria-label={`Remove ${source.name}`}
                    >
                      <TrashIcon size={14} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="settings-marketplace-panel">
          <div className="settings-marketplace-panel-header">
            <div>
              <h3>Direct Claude Repos</h3>
              <p>Install a GitHub or local Claude plugin, skill, or MCP repo directly. Use this for repos like `JuliusBrussee/caveman`.</p>
            </div>
          </div>
          <div className="settings-marketplace-warning settings-marketplace-warning-inline">
            Hook-only Claude plugins may install successfully but still not add slash commands or tools in Xpdite yet.
          </div>
          <div className="settings-marketplace-source-form settings-marketplace-direct-form">
            <input
              value={repoInput}
              onChange={(event) => setRepoInput(event.target.value)}
              placeholder="GitHub repo, URL, or local path, e.g. JuliusBrussee/caveman"
            />
            <button onClick={() => void handleInstallRepo()} disabled={busyKey === 'install-repo'}>
              Install Repo
            </button>
          </div>
        </section>

        <section className="settings-marketplace-panel">
          <div className="settings-marketplace-panel-header">
            <div>
              <h3>Direct MCP Packages</h3>
              <p>Install MCP servers straight from `npx` or `uvx`. Paste the package plus any args here. Use `${'{SECRET_NAME}'}` in args or env values to trigger the secret modal.</p>
            </div>
          </div>
          <div className="settings-marketplace-warning settings-marketplace-warning-inline">
            Official registry entries verify publisher ownership, not full code safety. Review third-party packages before installing them.
          </div>
          <div className="settings-marketplace-package-form">
            <div className="settings-marketplace-filter-row">
              {(['npx', 'uvx'] as PackageRunner[]).map((runner) => (
                <button
                  key={runner}
                  className={packageRunner === runner ? 'active' : ''}
                  onClick={() => setPackageRunner(runner)}
                >
                  {runner}
                </button>
              ))}
            </div>
            <input
              value={packageInput}
              onChange={(event) => setPackageInput(event.target.value)}
              placeholder={packageRunner === 'npx'
                ? 'Package/args, e.g. mcp-server-sqlite --db-path C:/tmp/test.db or OPENAI_API_KEY=${OPENAI_API_KEY} @scope/server'
                : 'Package/args, e.g. mcp-server-git --repository C:/repo or OPENAI_API_KEY=${OPENAI_API_KEY} mcp-server-foo'}
            />
            <button onClick={() => void handleInstallPackage()} disabled={busyKey === 'install-package'}>
              Install Package
            </button>
          </div>
        </section>

        <section className="settings-marketplace-panel">
          <div className="settings-marketplace-panel-header settings-marketplace-panel-header-row">
            <div className="settings-marketplace-catalog-header">
              <h3>Catalog</h3>
              <span className="settings-marketplace-count">
                {filteredCatalog.length} item{filteredCatalog.length === 1 ? '' : 's'}
              </span>
            </div>
            <div className="settings-marketplace-catalog-controls">
              <input
                value={catalogQuery}
                onChange={(event) => setCatalogQuery(event.target.value)}
                placeholder="Search catalog"
              />
            </div>
          </div>
          <div className="settings-marketplace-card-list">
            {loading && <div className="settings-marketplace-empty">Loading marketplace catalog...</div>}
            {!loading && filteredCatalog.length === 0 && (
              <div className="settings-marketplace-empty">No marketplace items matched the current filter.</div>
            )}
            {visibleCatalog.map((item) => {
              const install = item.install;
              const installBusyKey = `install:${item.source_id}:${item.manifest_item_id}`;
              return (
                <div key={`${item.source_id}:${item.manifest_item_id}`} className="settings-marketplace-item-card">
                  <div className="settings-marketplace-item-top">
                    <div className="settings-marketplace-item-copy">
                      <h4>{item.display_name}</h4>
                      <p>{item.description || 'No description provided.'}</p>
                    </div>
                    <div className="settings-marketplace-actions">
                      {install ? (
                        <span className="settings-marketplace-installed">Installed</span>
                      ) : (
                        <button onClick={() => void handleInstall(item)} disabled={busyKey === installBusyKey}>
                          Install
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="settings-marketplace-meta-row">
                    <span>{item.component_counts.skills} skill(s)</span>
                    <span>{item.component_counts.mcp_servers} MCP server(s)</span>
                    {item.required_secrets.length > 0 && <span>{item.required_secrets.length} secret(s) required</span>}
                  </div>
                  {item.compatibility_warnings.map((warning) => (
                    <div key={warning} className="settings-marketplace-warning">{warning}</div>
                  ))}
                </div>
              );
            })}
            {!loading && visibleCatalog.length < filteredCatalog.length && (
              <button
                className="settings-marketplace-load-more"
                onClick={() => setCatalogVisibleCount((count) => count + 100)}
              >
                Load More
              </button>
            )}
          </div>
        </section>

        <section className="settings-marketplace-panel">
          <div className="settings-marketplace-panel-header">
            <div>
              <h3>Installed</h3>
              <p>Enable, disable, update, or remove installed marketplace items.</p>
            </div>
          </div>
          <div className="settings-marketplace-card-list">
            {!loading && installs.length === 0 && (
              <div className="settings-marketplace-empty">No marketplace items are installed yet.</div>
            )}
            {installs.map((install) => {
              const counts = getInstallCounts(install);
              const slashCommands = getInstallSlashCommands(install);
              const originLabel = getInstallOriginLabel(install);
              const installWarnings = getInstallWarnings(install);
              return (
              <div key={install.id} className="settings-marketplace-item-card">
                <div className="settings-marketplace-item-top">
                  <div className="settings-marketplace-item-copy">
                    <div className="settings-marketplace-pill">{labelForKind(install.item_kind)}</div>
                    <h4>{install.display_name}</h4>
                    <p>Status: {install.status}</p>
                  </div>
                  <div className="settings-marketplace-actions">
                    <button onClick={() => void handleUpdate(install.id)} disabled={busyKey === `update:${install.id}`}>
                      Update
                    </button>
                    <button
                      onClick={() => void handleSetEnabled(install.id, !install.enabled)}
                      disabled={busyKey === `${install.enabled ? 'disable' : 'enable'}:${install.id}`}
                    >
                      {install.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button onClick={() => void handleDeleteInstall(install.id)} disabled={busyKey === `delete-install:${install.id}`}>
                      Remove
                    </button>
                  </div>
                </div>
                <div className="settings-marketplace-meta-row">
                  {slashCommands.length > 0 && (
                    <span>
                      {slashCommands.length === 1 ? 'Command' : 'Commands'}: {slashCommands.map((command) => `/${command}`).join(', ')}
                    </span>
                  )}
                  {counts.skills > 0 && <span>{counts.skills} skill(s)</span>}
                  {counts.commands > 0 && <span>{counts.commands} command(s)</span>}
                  {counts.mcpServers > 0 && <span>{counts.mcpServers} MCP server(s)</span>}
                  {originLabel && <span>{originLabel}</span>}
                  {install.required_secrets && install.required_secrets.length > 0 && (
                    <button className="settings-marketplace-link-button" onClick={() => void handleInstallSecrets(install)}>
                      Configure Secrets
                    </button>
                  )}
                </div>
                {install.last_error && <div className="settings-marketplace-warning">{install.last_error}</div>}
                {installWarnings.map((warning) => (
                  <div key={`${install.id}:${warning}`} className="settings-marketplace-warning">{warning}</div>
                ))}
                {install.status === 'manual_auth_required' && (
                  <div className="settings-marketplace-warning">
                    This item needs secrets or auth data that Xpdite could not resolve automatically.
                  </div>
                )}
              </div>
            )})}
          </div>
        </section>
      </div>

      {secretModal && (
        <div className="settings-marketplace-modal-overlay" onClick={closeSecretModal}>
          <div className="settings-marketplace-modal" onClick={(event) => event.stopPropagation()}>
            <div className="settings-marketplace-modal-header">
              <div>
                <h3>{secretModal.title}</h3>
                <p>{secretModal.subtitle}</p>
              </div>
              <button
                type="button"
                className="settings-marketplace-modal-close"
                onClick={closeSecretModal}
              >
                x
              </button>
            </div>
            <div className="settings-marketplace-modal-body">
              {secretModal.secretNames.map((secretName) => (
                <label key={secretName} className="settings-marketplace-modal-field">
                  <span>{secretName}</span>
                  <input
                    type="password"
                    value={secretValues[secretName] ?? ''}
                    onChange={(event) => {
                      const nextValue = event.target.value;
                      setSecretValues((current) => ({ ...current, [secretName]: nextValue }));
                      if (secretError) {
                        setSecretError('');
                      }
                    }}
                    placeholder={`Enter ${secretName}`}
                  />
                </label>
              ))}
              {secretError && <div className="settings-marketplace-error">{secretError}</div>}
            </div>
            <div className="settings-marketplace-modal-footer">
              <button type="button" onClick={closeSecretModal}>Cancel</button>
              <button type="button" onClick={submitSecretModal}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsMarketplace;
