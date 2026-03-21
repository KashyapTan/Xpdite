"""Tests for external MCP connectors service."""

from unittest.mock import MagicMock, patch, AsyncMock
import pytest


class TestExternalConnectorsService:
    """Tests for ExternalConnectorService methods."""

    def test_get_all_connectors_returns_all_with_status(self):
        """Test that get_all_connectors returns all connectors with their current status."""
        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        mock_mcp_manager = MagicMock()
        mock_mcp_manager.is_server_connected.return_value = False

        with (
            patch("source.services.external_connectors.db", mock_db),
            patch(
                "source.mcp_integration.manager.mcp_manager",
                mock_mcp_manager,
            ),
        ):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            connectors = service.get_all_connectors()

            # Should have at least Everything (Demo)
            assert len(connectors) >= 1
            everything = next(
                (c for c in connectors if c["name"] == "everything"), None
            )
            assert everything is not None
            assert everything["display_name"] == "Everything (Demo)"
            assert everything["enabled"] is False
            assert everything["connected"] is False

    def test_is_enabled_returns_true_when_setting_is_true(self):
        """Test is_enabled returns True when the setting is 'true'."""
        mock_db = MagicMock()
        mock_db.get_setting.return_value = "true"

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            result = service.is_enabled("everything")

            assert result is True
            mock_db.get_setting.assert_called_with(
                "external_connector:everything:enabled"
            )

    def test_is_enabled_returns_false_when_setting_is_false(self):
        """Test is_enabled returns False when the setting is 'false'."""
        mock_db = MagicMock()
        mock_db.get_setting.return_value = "false"

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            result = service.is_enabled("everything")

            assert result is False

    def test_is_enabled_returns_false_when_setting_is_none(self):
        """Test is_enabled returns False when the setting doesn't exist."""
        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            result = service.is_enabled("everything")

            assert result is False

    def test_set_enabled_stores_setting(self):
        """Test set_enabled stores the setting in the database."""
        mock_db = MagicMock()

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            service.set_enabled("everything", True)

            mock_db.set_setting.assert_called_with(
                "external_connector:everything:enabled", "true"
            )

    def test_set_enabled_raises_for_unknown_connector(self):
        """Test set_enabled raises ValueError for unknown connector."""
        mock_db = MagicMock()

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            with pytest.raises(ValueError, match="Unknown connector"):
                service.set_enabled("nonexistent", True)

    def test_get_connector_returns_connector_definition(self):
        """Test get_connector returns the connector definition."""
        from source.services.external_connectors import ExternalConnectorService

        service = ExternalConnectorService()
        connector = service.get_connector("everything")

        assert connector is not None
        assert connector["name"] == "everything"
        assert connector["command"] == "npx"
        assert "@modelcontextprotocol/server-everything" in connector["args"]

    def test_get_connector_returns_none_for_unknown(self):
        """Test get_connector returns None for unknown connector."""
        from source.services.external_connectors import ExternalConnectorService

        service = ExternalConnectorService()
        connector = service.get_connector("nonexistent")

        assert connector is None

    def test_get_enabled_connectors_returns_enabled_only(self):
        """Test get_enabled_connectors returns only enabled connector names."""
        mock_db = MagicMock()

        def mock_get_setting(key):
            if key == "external_connector:everything:enabled":
                return "true"
            return None

        mock_db.get_setting.side_effect = mock_get_setting

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            enabled = service.get_enabled_connectors()

            assert "everything" in enabled

    def test_set_last_error_stores_error(self):
        """Test set_last_error stores error in database."""
        mock_db = MagicMock()

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            service.set_last_error("everything", "Connection timeout")

            mock_db.set_setting.assert_called_with(
                "external_connector:everything:last_error", "Connection timeout"
            )

    def test_set_last_error_deletes_when_none(self):
        """Test set_last_error deletes the setting when error is None."""
        mock_db = MagicMock()

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import ExternalConnectorService

            service = ExternalConnectorService()
            service.set_last_error("everything", None)

            mock_db.delete_setting.assert_called_with(
                "external_connector:everything:last_error"
            )


class TestConnectExternalConnector:
    """Tests for connect_external_connector function."""

    @pytest.mark.asyncio
    async def test_connect_returns_error_for_unknown_connector(self):
        """Test connecting unknown connector returns error."""
        from source.services.external_connectors import connect_external_connector

        result = await connect_external_connector("nonexistent")

        assert result["success"] is False
        assert "Unknown connector" in result["error"]

    @pytest.mark.asyncio
    async def test_connect_calls_mcp_manager(self):
        """Test connect calls mcp_manager.connect_server."""
        mock_mcp_manager = MagicMock()
        mock_mcp_manager.connect_server = AsyncMock()
        mock_mcp_manager.is_server_connected.return_value = True

        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        with (
            patch("source.mcp_integration.manager.mcp_manager", mock_mcp_manager),
            patch("source.services.external_connectors.db", mock_db),
            patch(
                "source.services.external_connectors.external_connectors.set_enabled"
            ),
            patch(
                "source.services.external_connectors.external_connectors.set_last_error"
            ),
        ):
            from source.services.external_connectors import connect_external_connector

            result = await connect_external_connector("everything")

            assert result["success"] is True
            mock_mcp_manager.connect_server.assert_called_once()
            call_args = mock_mcp_manager.connect_server.call_args
            assert call_args.kwargs["server_name"] == "everything"
            assert call_args.kwargs["command"] == "npx"

    @pytest.mark.asyncio
    async def test_connect_marks_enabled_on_success(self):
        """Test connect marks connector as enabled on success."""
        mock_mcp_manager = MagicMock()
        mock_mcp_manager.connect_server = AsyncMock()
        mock_mcp_manager.is_server_connected.return_value = True

        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        with (
            patch("source.mcp_integration.manager.mcp_manager", mock_mcp_manager),
            patch("source.services.external_connectors.db", mock_db),
        ):
            from source.services.external_connectors import connect_external_connector

            result = await connect_external_connector("everything")

            assert result["success"] is True
            mock_db.set_setting.assert_any_call(
                "external_connector:everything:enabled", "true"
            )

    @pytest.mark.asyncio
    async def test_connect_returns_error_when_server_not_connected(self):
        """Test connect returns error when server fails to connect."""
        mock_mcp_manager = MagicMock()
        mock_mcp_manager.connect_server = AsyncMock()
        mock_mcp_manager.is_server_connected.return_value = False  # Connection failed

        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        with (
            patch("source.mcp_integration.manager.mcp_manager", mock_mcp_manager),
            patch("source.services.external_connectors.db", mock_db),
        ):
            from source.services.external_connectors import connect_external_connector

            result = await connect_external_connector("everything")

            assert result["success"] is False
            assert "Connection failed" in result["error"]


class TestDisconnectExternalConnector:
    """Tests for disconnect_external_connector function."""

    @pytest.mark.asyncio
    async def test_disconnect_returns_error_for_unknown_connector(self):
        """Test disconnecting unknown connector returns error."""
        from source.services.external_connectors import disconnect_external_connector

        result = await disconnect_external_connector("nonexistent")

        assert result["success"] is False
        assert "Unknown connector" in result["error"]

    @pytest.mark.asyncio
    async def test_disconnect_calls_mcp_manager_when_connected(self):
        """Test disconnect calls mcp_manager.disconnect_server when connected."""
        mock_mcp_manager = MagicMock()
        mock_mcp_manager.disconnect_server = AsyncMock()
        mock_mcp_manager.is_server_connected.return_value = True

        mock_db = MagicMock()

        with (
            patch("source.mcp_integration.manager.mcp_manager", mock_mcp_manager),
            patch("source.services.external_connectors.db", mock_db),
        ):
            from source.services.external_connectors import (
                disconnect_external_connector,
            )

            result = await disconnect_external_connector("everything")

            assert result["success"] is True
            mock_mcp_manager.disconnect_server.assert_called_once_with("everything")

    @pytest.mark.asyncio
    async def test_disconnect_marks_disabled(self):
        """Test disconnect marks connector as disabled."""
        mock_mcp_manager = MagicMock()
        mock_mcp_manager.disconnect_server = AsyncMock()
        mock_mcp_manager.is_server_connected.return_value = False

        mock_db = MagicMock()

        with (
            patch("source.mcp_integration.manager.mcp_manager", mock_mcp_manager),
            patch("source.services.external_connectors.db", mock_db),
        ):
            from source.services.external_connectors import (
                disconnect_external_connector,
            )

            result = await disconnect_external_connector("everything")

            assert result["success"] is True
            mock_db.set_setting.assert_called_with(
                "external_connector:everything:enabled", "false"
            )


class TestInitExternalConnectors:
    """Tests for init_external_connectors function."""

    @pytest.mark.asyncio
    async def test_init_does_nothing_when_no_connectors_enabled(self):
        """Test init does nothing when no connectors are enabled."""
        mock_db = MagicMock()
        mock_db.get_setting.return_value = None

        with patch("source.services.external_connectors.db", mock_db):
            from source.services.external_connectors import init_external_connectors

            # Should complete without error
            await init_external_connectors()

    @pytest.mark.asyncio
    async def test_init_connects_enabled_connectors(self):
        """Test init connects all enabled connectors."""
        mock_mcp_manager = MagicMock()
        mock_mcp_manager.connect_server = AsyncMock()
        mock_mcp_manager.is_server_connected.return_value = True

        mock_db = MagicMock()

        def mock_get_setting(key):
            if key == "external_connector:everything:enabled":
                return "true"
            return None

        mock_db.get_setting.side_effect = mock_get_setting

        with (
            patch("source.mcp_integration.manager.mcp_manager", mock_mcp_manager),
            patch("source.services.external_connectors.db", mock_db),
        ):
            from source.services.external_connectors import init_external_connectors

            await init_external_connectors()

            # Should have called connect_server for everything
            mock_mcp_manager.connect_server.assert_called()
