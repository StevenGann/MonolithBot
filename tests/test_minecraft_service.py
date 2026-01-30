"""
Unit tests for bot/services/minecraft.py - Minecraft server status client.

Tests cover:
    - MinecraftServerStatus dataclass
    - MinecraftServerState dataclass
    - MinecraftClient single-server queries
    - MinecraftService multi-server management and failover
    - Player join detection
    - State management
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.minecraft import (
    MinecraftClient,
    MinecraftService,
    MinecraftServerStatus,
    MinecraftServerState,
    MinecraftError,
    MinecraftConnectionError,
    MinecraftTimeoutError,
)
from bot.config import MinecraftServerConfig


# =============================================================================
# MinecraftServerStatus Tests
# =============================================================================


class TestMinecraftServerStatus:
    """Tests for MinecraftServerStatus dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic status object."""
        status = MinecraftServerStatus(online=True)
        assert status.online is True
        assert status.player_count == 0
        assert status.max_players == 0
        assert status.player_names == set()
        assert status.players_hidden is False
        assert status.motd == ""
        assert status.version == ""
        assert status.latency_ms == 0.0

    def test_full_creation(self) -> None:
        """Test creating a fully populated status object."""
        status = MinecraftServerStatus(
            online=True,
            player_count=5,
            max_players=20,
            player_names={"Steve", "Alex", "Notch"},
            players_hidden=False,
            motd="Welcome to the server!",
            version="1.20.4",
            latency_ms=45.5,
        )
        assert status.online is True
        assert status.player_count == 5
        assert status.max_players == 20
        assert len(status.player_names) == 3
        assert "Steve" in status.player_names
        assert status.motd == "Welcome to the server!"
        assert status.version == "1.20.4"
        assert status.latency_ms == 45.5

    def test_offline_status(self) -> None:
        """Test creating an offline status object."""
        status = MinecraftServerStatus(online=False)
        assert status.online is False
        assert status.player_count == 0

    def test_hidden_players(self) -> None:
        """Test status when server hides player list."""
        status = MinecraftServerStatus(
            online=True,
            player_count=10,
            max_players=50,
            player_names=set(),
            players_hidden=True,
        )
        assert status.players_hidden is True
        assert status.player_count == 10
        assert len(status.player_names) == 0


# =============================================================================
# MinecraftServerState Tests
# =============================================================================


class TestMinecraftServerState:
    """Tests for MinecraftServerState dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic state object."""
        state = MinecraftServerState(
            name="Survival",
            urls=["localhost:25565"],
        )
        assert state.name == "Survival"
        assert state.urls == ["localhost:25565"]
        assert state.active_url is None
        assert state.online is None
        assert state.last_online is None
        assert state.went_offline is None
        assert state.previous_players == set()
        assert state.last_status is None

    def test_multiple_urls(self) -> None:
        """Test state with multiple URLs for failover."""
        state = MinecraftServerState(
            name="Survival",
            urls=["primary.example.com:25565", "backup.example.com:25565"],
        )
        assert len(state.urls) == 2
        assert state.urls[0] == "primary.example.com:25565"

    def test_state_with_timestamps(self) -> None:
        """Test state with timestamp values."""
        now = datetime.now(timezone.utc)
        state = MinecraftServerState(
            name="Survival",
            urls=["localhost:25565"],
            online=True,
            last_online=now,
        )
        assert state.online is True
        assert state.last_online == now

    def test_previous_players_set(self) -> None:
        """Test state with previous player set."""
        state = MinecraftServerState(
            name="Survival",
            urls=["localhost:25565"],
            previous_players={"Steve", "Alex"},
        )
        assert len(state.previous_players) == 2
        assert "Steve" in state.previous_players


# =============================================================================
# MinecraftClient Tests
# =============================================================================


class TestMinecraftClientInit:
    """Tests for MinecraftClient initialization."""

    def test_basic_init(self) -> None:
        """Test basic client initialization."""
        client = MinecraftClient("localhost:25565")
        assert client.address == "localhost:25565"
        assert client.timeout == 5.0

    def test_custom_timeout(self) -> None:
        """Test client with custom timeout."""
        client = MinecraftClient("localhost:25565", timeout=10.0)
        assert client.timeout == 10.0

    def test_address_without_port(self) -> None:
        """Test client with address without port."""
        client = MinecraftClient("mc.example.com")
        assert client.address == "mc.example.com"


class TestMinecraftClientCleanMotd:
    """Tests for MinecraftClient._clean_motd static method."""

    def test_clean_simple_motd(self) -> None:
        """Test cleaning a simple MOTD."""
        result = MinecraftClient._clean_motd("Welcome to the server!")
        assert result == "Welcome to the server!"

    def test_clean_motd_with_color_codes(self) -> None:
        """Test removing Minecraft color codes."""
        result = MinecraftClient._clean_motd("§aWelcome §bto §cthe §dserver!")
        assert result == "Welcome to the server!"

    def test_clean_motd_with_formatting_codes(self) -> None:
        """Test removing formatting codes."""
        result = MinecraftClient._clean_motd("§l§nBold and Underline§r Normal")
        assert result == "Bold and Underline Normal"

    def test_clean_motd_with_whitespace(self) -> None:
        """Test stripping whitespace."""
        result = MinecraftClient._clean_motd("  Server MOTD  ")
        assert result == "Server MOTD"


class TestMinecraftClientCheckStatus:
    """Tests for MinecraftClient.check_status method."""

    @pytest.mark.asyncio
    async def test_check_status_success(self) -> None:
        """Test successful status check."""
        mock_response = MagicMock()
        mock_response.players.online = 5
        mock_response.players.max = 20
        mock_response.players.sample = [
            MagicMock(name="Steve"),
            MagicMock(name="Alex"),
        ]
        mock_response.motd = "Welcome!"
        mock_response.version.name = "1.20.4"
        mock_response.latency = 45.5

        with patch("bot.services.minecraft.JavaServer") as mock_java_server:
            mock_server = MagicMock()
            mock_server.async_status = AsyncMock(return_value=mock_response)
            mock_java_server.lookup.return_value = mock_server

            client = MinecraftClient("localhost:25565")
            status = await client.check_status()

            assert status.online is True
            assert status.player_count == 5
            assert status.max_players == 20
            assert status.version == "1.20.4"
            assert status.latency_ms == 45.5

    @pytest.mark.asyncio
    async def test_check_status_connection_error(self) -> None:
        """Test handling connection errors."""
        with patch("bot.services.minecraft.JavaServer") as mock_java_server:
            mock_server = MagicMock()
            mock_server.async_status = AsyncMock(
                side_effect=OSError("Connection refused")
            )
            mock_java_server.lookup.return_value = mock_server

            client = MinecraftClient("localhost:25565")

            with pytest.raises(MinecraftConnectionError) as exc_info:
                await client.check_status()

            assert "Cannot connect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_status_timeout(self) -> None:
        """Test handling timeout errors."""
        with patch("bot.services.minecraft.JavaServer") as mock_java_server:
            mock_server = MagicMock()
            mock_server.async_status = AsyncMock(side_effect=TimeoutError())
            mock_java_server.lookup.return_value = mock_server

            client = MinecraftClient("localhost:25565")

            with pytest.raises(MinecraftTimeoutError) as exc_info:
                await client.check_status()

            assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_status_hidden_players(self) -> None:
        """Test handling servers with hidden player lists."""
        mock_response = MagicMock()
        mock_response.players.online = 10
        mock_response.players.max = 50
        mock_response.players.sample = None  # No sample = hidden
        mock_response.motd = "Server"
        mock_response.version.name = "1.20.4"
        mock_response.latency = 30.0

        with patch("bot.services.minecraft.JavaServer") as mock_java_server:
            mock_server = MagicMock()
            mock_server.async_status = AsyncMock(return_value=mock_response)
            mock_java_server.lookup.return_value = mock_server

            client = MinecraftClient("localhost:25565")
            status = await client.check_status()

            assert status.online is True
            assert status.player_count == 10
            assert status.players_hidden is True
            assert len(status.player_names) == 0


# =============================================================================
# MinecraftService Tests
# =============================================================================


class TestMinecraftServiceInit:
    """Tests for MinecraftService initialization."""

    def test_basic_init(self) -> None:
        """Test basic service initialization."""
        configs = [
            MinecraftServerConfig(name="Survival", urls=["localhost:25565"]),
        ]
        service = MinecraftService(configs)

        assert len(service.get_all_servers()) == 1
        state = service.get_server_state("Survival")
        assert state is not None
        assert state.name == "Survival"

    def test_multiple_servers(self) -> None:
        """Test service with multiple servers."""
        configs = [
            MinecraftServerConfig(name="Survival", urls=["mc1.example.com"]),
            MinecraftServerConfig(name="Creative", urls=["mc2.example.com"]),
            MinecraftServerConfig(name="Minigames", urls=["mc3.example.com"]),
        ]
        service = MinecraftService(configs)

        assert len(service.get_all_servers()) == 3
        assert "Survival" in service.get_server_names()
        assert "Creative" in service.get_server_names()
        assert "Minigames" in service.get_server_names()

    def test_empty_servers(self) -> None:
        """Test service with no servers."""
        service = MinecraftService([])
        assert len(service.get_all_servers()) == 0


class TestMinecraftServiceServerAccess:
    """Tests for MinecraftService server access methods."""

    @pytest.fixture
    def service(self) -> MinecraftService:
        """Create a service with test servers."""
        configs = [
            MinecraftServerConfig(name="Survival", urls=["mc1.example.com"]),
            MinecraftServerConfig(name="Creative", urls=["mc2.example.com"]),
        ]
        return MinecraftService(configs)

    def test_get_server_state_exists(self, service: MinecraftService) -> None:
        """Test getting state for existing server."""
        state = service.get_server_state("Survival")
        assert state is not None
        assert state.name == "Survival"

    def test_get_server_state_not_exists(self, service: MinecraftService) -> None:
        """Test getting state for non-existent server."""
        state = service.get_server_state("NonExistent")
        assert state is None

    def test_get_all_servers(self, service: MinecraftService) -> None:
        """Test getting all server states."""
        servers = service.get_all_servers()
        assert len(servers) == 2
        names = [s.name for s in servers]
        assert "Survival" in names
        assert "Creative" in names

    def test_get_server_names(self, service: MinecraftService) -> None:
        """Test getting server names."""
        names = service.get_server_names()
        assert len(names) == 2
        assert "Survival" in names
        assert "Creative" in names


class TestMinecraftServiceCheckHealth:
    """Tests for MinecraftService.check_health with failover."""

    @pytest.fixture
    def service_with_failover(self) -> MinecraftService:
        """Create a service with failover URLs."""
        configs = [
            MinecraftServerConfig(
                name="Survival",
                urls=["primary.example.com:25565", "backup.example.com:25565"],
            ),
        ]
        return MinecraftService(configs)

    @pytest.mark.asyncio
    async def test_check_health_primary_success(
        self, service_with_failover: MinecraftService
    ) -> None:
        """Test health check succeeds with primary URL."""
        mock_status = MinecraftServerStatus(
            online=True,
            player_count=5,
            max_players=20,
            version="1.20.4",
        )

        with patch.object(
            MinecraftClient, "check_status", new_callable=AsyncMock
        ) as mock_check:
            mock_check.return_value = mock_status

            status = await service_with_failover.check_health("Survival")

            assert status.online is True
            assert status.player_count == 5

            state = service_with_failover.get_server_state("Survival")
            assert state.active_url == "primary.example.com:25565"

    @pytest.mark.asyncio
    async def test_check_health_failover_to_backup(
        self, service_with_failover: MinecraftService
    ) -> None:
        """Test health check fails over to backup URL."""
        mock_status = MinecraftServerStatus(
            online=True,
            player_count=3,
            max_players=20,
            version="1.20.4",
        )

        call_count = 0

        async def mock_check_status(self: MinecraftClient) -> MinecraftServerStatus:
            nonlocal call_count
            call_count += 1
            if "primary" in self.address:
                raise MinecraftConnectionError("Connection refused")
            return mock_status

        with patch.object(MinecraftClient, "check_status", mock_check_status):
            status = await service_with_failover.check_health("Survival")

            assert status.online is True
            assert call_count == 2  # Tried primary, then backup

            state = service_with_failover.get_server_state("Survival")
            assert state.active_url == "backup.example.com:25565"

    @pytest.mark.asyncio
    async def test_check_health_all_urls_fail(
        self, service_with_failover: MinecraftService
    ) -> None:
        """Test health check raises when all URLs fail."""
        with patch.object(
            MinecraftClient,
            "check_status",
            new_callable=AsyncMock,
            side_effect=MinecraftConnectionError("Connection refused"),
        ):
            with pytest.raises(MinecraftConnectionError) as exc_info:
                await service_with_failover.check_health("Survival")

            assert "All URLs failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_check_health_unknown_server(
        self, service_with_failover: MinecraftService
    ) -> None:
        """Test health check raises for unknown server."""
        with pytest.raises(MinecraftError) as exc_info:
            await service_with_failover.check_health("NonExistent")

        assert "Unknown server" in str(exc_info.value)


class TestMinecraftServicePlayerTracking:
    """Tests for MinecraftService player tracking methods."""

    @pytest.fixture
    def service(self) -> MinecraftService:
        """Create a service for player tracking tests."""
        configs = [
            MinecraftServerConfig(name="Survival", urls=["localhost:25565"]),
        ]
        return MinecraftService(configs)

    def test_detect_player_joins_first_check(self, service: MinecraftService) -> None:
        """Test join detection on first check returns all players."""
        current = {"Steve", "Alex"}
        new_players = service.detect_player_joins("Survival", current)

        # First check - all players are "new"
        assert new_players == {"Steve", "Alex"}

        # State should be updated
        state = service.get_server_state("Survival")
        assert state.previous_players == {"Steve", "Alex"}

    def test_detect_player_joins_new_player(self, service: MinecraftService) -> None:
        """Test detecting a new player join."""
        # Set up initial state
        service.update_players("Survival", {"Steve", "Alex"})

        # New player joins
        current = {"Steve", "Alex", "Notch"}
        new_players = service.detect_player_joins("Survival", current)

        assert new_players == {"Notch"}

    def test_detect_player_joins_no_change(self, service: MinecraftService) -> None:
        """Test no joins detected when players unchanged."""
        service.update_players("Survival", {"Steve", "Alex"})

        current = {"Steve", "Alex"}
        new_players = service.detect_player_joins("Survival", current)

        assert new_players == set()

    def test_detect_player_joins_player_left(self, service: MinecraftService) -> None:
        """Test join detection when player leaves (not a join)."""
        service.update_players("Survival", {"Steve", "Alex", "Notch"})

        # Notch leaves
        current = {"Steve", "Alex"}
        new_players = service.detect_player_joins("Survival", current)

        assert new_players == set()

    def test_detect_player_leaves(self, service: MinecraftService) -> None:
        """Test detecting players who left."""
        service.update_players("Survival", {"Steve", "Alex", "Notch"})

        current = {"Steve"}  # Alex and Notch left
        left_players = service.detect_player_leaves("Survival", current)

        assert left_players == {"Alex", "Notch"}

    def test_detect_player_joins_unknown_server(
        self, service: MinecraftService
    ) -> None:
        """Test join detection for unknown server returns empty."""
        result = service.detect_player_joins("NonExistent", {"Steve"})
        assert result == set()

    def test_update_players(self, service: MinecraftService) -> None:
        """Test directly updating player set."""
        service.update_players("Survival", {"Steve", "Alex"})

        state = service.get_server_state("Survival")
        assert state.previous_players == {"Steve", "Alex"}


class TestMinecraftServiceStateManagement:
    """Tests for MinecraftService state management methods."""

    @pytest.fixture
    def service(self) -> MinecraftService:
        """Create a service for state management tests."""
        configs = [
            MinecraftServerConfig(name="Survival", urls=["localhost:25565"]),
        ]
        return MinecraftService(configs)

    def test_mark_online(self, service: MinecraftService) -> None:
        """Test marking server as online."""
        service.mark_online("Survival")

        state = service.get_server_state("Survival")
        assert state.online is True
        assert state.last_online is not None
        assert state.went_offline is None

    def test_mark_offline(self, service: MinecraftService) -> None:
        """Test marking server as offline."""
        # First mark as online
        service.mark_online("Survival")

        # Then mark as offline
        service.mark_offline("Survival")

        state = service.get_server_state("Survival")
        assert state.online is False
        assert state.went_offline is not None

    def test_mark_offline_from_unknown(self, service: MinecraftService) -> None:
        """Test marking offline from unknown state sets went_offline."""
        service.mark_offline("Survival")

        state = service.get_server_state("Survival")
        assert state.online is False
        assert state.went_offline is not None

    def test_get_downtime(self, service: MinecraftService) -> None:
        """Test getting downtime duration."""
        service.mark_offline("Survival")

        # Wait a tiny bit to have some downtime
        downtime = service.get_downtime("Survival")
        assert downtime is not None
        assert downtime >= 0

    def test_get_downtime_when_online(self, service: MinecraftService) -> None:
        """Test get_downtime returns None when online."""
        service.mark_online("Survival")

        downtime = service.get_downtime("Survival")
        assert downtime is None

    def test_reset_state(self, service: MinecraftService) -> None:
        """Test resetting server state."""
        # Set up some state
        service.mark_online("Survival")
        service.update_players("Survival", {"Steve"})
        state = service.get_server_state("Survival")
        state.active_url = "localhost:25565"

        # Reset
        service.reset_state("Survival")

        state = service.get_server_state("Survival")
        assert state.active_url is None
        assert state.online is None
        assert state.last_online is None
        assert state.previous_players == set()
        # URLs should be preserved
        assert state.urls == ["localhost:25565"]
