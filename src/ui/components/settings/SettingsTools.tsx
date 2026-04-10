import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import { ChevronRightIcon } from '../icons/AppIcons';
import '../../CSS/settings/SettingsTools.css';

interface McpServer {
  server: string;
  tools: string[];
}

const SettingsTools: React.FC = () => {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [alwaysOn, setAlwaysOn] = useState<string[]>([]);
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(true);
  // Track which server sections are expanded
  const [expandedServers, setExpandedServers] = useState<Set<string>>(new Set());

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [mcpServers, settings] = await Promise.all([
          api.getMcpServers(),
          api.getToolsSettings()
        ]);
        setServers(mcpServers);
        setAlwaysOn(settings.always_on);
        setTopK(settings.top_k);
        
        // Expand all servers by default
        // setExpandedServers(new Set(mcpServers.map(s => s.server)));
      } catch (error) {
        console.error("Failed to load tools data", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const saveSettings = async (newAlwaysOn: string[], newTopK: number) => {
    setAlwaysOn(newAlwaysOn);
    setTopK(newTopK);
    await api.setToolsSettings(newAlwaysOn, newTopK);
  };

  const toggleTool = (toolName: string) => {
    const newAlwaysOn = alwaysOn.includes(toolName)
      ? alwaysOn.filter(t => t !== toolName)
      : [...alwaysOn, toolName];
    saveSettings(newAlwaysOn, topK);
  };

  const toggleServer = (serverTools: string[]) => {
    const allEnabled = serverTools.every(t => alwaysOn.includes(t));
    
    let newAlwaysOn = [...alwaysOn];
    if (allEnabled) {
      // Disable all
      newAlwaysOn = newAlwaysOn.filter(t => !serverTools.includes(t));
    } else {
      // Enable all (add missing ones)
      const missing = serverTools.filter(t => !alwaysOn.includes(t));
      newAlwaysOn = [...newAlwaysOn, ...missing];
    }
    saveSettings(newAlwaysOn, topK);
  };

  const toggleExpand = (serverName: string) => {
    const newExpanded = new Set(expandedServers);
    if (newExpanded.has(serverName)) {
      newExpanded.delete(serverName);
    } else {
      newExpanded.add(serverName);
    }
    setExpandedServers(newExpanded);
  };

  const handleTopKChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseInt(e.target.value);
    if (!isNaN(val) && val >= 0 && val <= 20) {
      saveSettings(alwaysOn, val);
    }
  };

  if (loading) {
    return <div className="settings-tools-loading">Loading tools...</div>;
  }

  return (
    <div className="settings-tools-container">
      <div className="settings-tools-header">
        <h2>Tool Retrieval</h2>
        <p>Configure how tools are selected for Xpdite to use.</p>
      </div>

      <div className="settings-tools-section">
        <label className="settings-tools-label">
          Top K Retrieved Tools
          <span className="settings-tools-value">{topK}</span>
        </label>
        <div className="settings-tools-slider-container">
          <input
            type="range"
            min="0"
            max="10"
            value={topK}
            onChange={handleTopKChange}
            className="settings-tools-slider"
          />
          <span className="settings-tools-desc">
            Number of relevant tools to dynamically retrieve per query.
          </span>
        </div>
      </div>

      <div className="settings-tools-list">
        <h3>Connected MCP Servers</h3>
        {servers.map(server => {
          const isExpanded = expandedServers.has(server.server);
          const allEnabled = server.tools.length > 0 && server.tools.every(t => alwaysOn.includes(t));
          const someEnabled = server.tools.some(t => alwaysOn.includes(t));
          
          return (
            <div key={server.server} className="settings-tools-server-card">
              <div className="settings-tools-server-header">
                 <button 
                   type="button"
                   className={`settings-tools-expand-btn ${isExpanded ? 'expanded' : ''}`}
                   onClick={() => toggleExpand(server.server)}
                 >
                   <ChevronRightIcon size={16} />
                 </button>
                
                <div className="settings-tools-server-info" onClick={() => toggleExpand(server.server)}>
                  <span className="settings-tools-server-name">{server.server}</span>
                  <span className="settings-tools-count">{server.tools.length} tools</span>
                </div>

                <div 
                  className={`settings-tools-toggle ${allEnabled ? 'active' : someEnabled ? 'partial' : ''}`}
                  onClick={() => toggleServer(server.tools)}
                  title="Toggle all tools for this server"
                >
                  <div className="settings-tools-toggle-track">
                    <div className="settings-tools-toggle-thumb" />
                  </div>
                </div>
              </div>

              {isExpanded && (
                <div className="settings-tools-server-content">
                  {server.tools.map(tool => (
                    <div key={tool} className="settings-tools-item" onClick={() => toggleTool(tool)}>
                      <span className="settings-tools-name">{tool}</span>
                      
                      <div className={`settings-tools-toggle ${alwaysOn.includes(tool) ? 'active' : ''}`}>
                        <div className="settings-tools-toggle-track">
                          <div className="settings-tools-toggle-thumb" />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default SettingsTools;
