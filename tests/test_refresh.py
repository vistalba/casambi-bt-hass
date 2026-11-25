"""Test the offline-first start and the network refresh."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from CasambiBt import Group, NetworkAdditions, Scene, UnitControlType
from CasambiBt.errors import (
    AuthenticationError,
    CloudUnavailableError,
    NetworkUpdateError,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.casambi_bt.const import CONF_IMPORT_GROUPS, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import MockCasambi, drain, make_unit

pytestmark = pytest.mark.usefixtures("mock_bluetooth", "enable_bluetooth")


async def _setup(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await drain(hass)
    assert config_entry.state is ConfigEntryState.LOADED


async def test_starts_from_cache_and_refreshes(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
) -> None:
    """The network starts from the cache and checks the cloud afterwards."""
    await _setup(hass, config_entry)

    connect_kwargs = mock_casambi.connect.await_args.kwargs
    assert connect_kwargs["preferCache"] is True
    assert connect_kwargs["bleDeviceCallback"]() is not None
    mock_casambi.refreshNetwork.assert_awaited_once_with("secret-password")

    # Daily refresh.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(hours=25))
    await drain(hass)
    assert mock_casambi.refreshNetwork.await_count == 2
    assert mock_casambi.connect.await_count == 1


async def test_changed_network_reloads_entry(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
) -> None:
    """A changed configuration is applied by reloading the entry."""
    mock_casambi.refreshNetwork = AsyncMock(side_effect=[True, False])

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert mock_casambi.connect.await_count == 2


@pytest.mark.parametrize(
    "error",
    [
        CloudUnavailableError("offline"),
        CloudUnavailableError("Login failed: 503", 503),
        NetworkUpdateError("malformed"),
        AuthenticationError("Not authenticated!"),
        RuntimeError("bug"),
    ],
)
async def test_refresh_errors_keep_running(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
    error: Exception,
) -> None:
    """Without the cloud the network keeps running from the cache."""
    mock_casambi.refreshNetwork = AsyncMock(side_effect=error)

    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.available
    assert not hass.config_entries.flow.async_progress()


async def test_refresh_rejected_password_starts_reauth(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected password asks for a new one; the network keeps running."""
    mock_casambi.refreshNetwork = AsyncMock(
        side_effect=AuthenticationError("Login failed: 401", status_code=401)
    )

    await _setup(hass, config_entry)

    assert config_entry.runtime_data.available
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"


async def test_refresh_does_not_overlap(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
) -> None:
    """Refreshes don't run concurrently."""
    await _setup(hass, config_entry)
    api = config_entry.runtime_data
    calls = mock_casambi.refreshNetwork.await_count

    with patch.object(api, "_refreshing", True):
        await api.async_refresh_network()

    assert mock_casambi.refreshNetwork.await_count == calls


def _entity_ids(hass: HomeAssistant, config_entry: MockConfigEntry) -> list[str]:
    return sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(
            er.async_get(hass), config_entry.entry_id
        )
    )


@pytest.mark.parametrize("import_groups", [True, False])
async def test_additions_are_added_without_reload(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
    import_groups: bool,
) -> None:
    """Units, groups and scenes added in the app get entities right away."""
    config_entry = MockConfigEntry(
        domain=config_entry.domain,
        title=config_entry.title,
        data=config_entry.data,
        options={**config_entry.options, CONF_IMPORT_GROUPS: import_groups},
        unique_id=config_entry.unique_id,
        version=config_entry.version,
        minor_version=config_entry.minor_version,
    )
    lamp = make_unit(1, [UnitControlType.DIMMER])
    mock_casambi.units = [lamp]
    mock_casambi.groups = [Group(1, "Group 1", [lamp])]
    mock_casambi.scenes = [Scene(1, "Scene 1")]
    await _setup(hass, config_entry)
    before = _entity_ids(hass, config_entry)

    new_lamp = make_unit(2, [UnitControlType.DIMMER, UnitControlType.VERTICAL])
    new_group = Group(2, "Group 2", [lamp, new_lamp])
    new_scene = Scene(2, "Scene 2")

    async def _apply() -> NetworkAdditions:
        mock_casambi.units.append(new_lamp)
        mock_casambi.groups.append(new_group)
        mock_casambi.scenes.append(new_scene)
        return NetworkAdditions([new_lamp], [new_group], [new_scene])

    mock_casambi.refreshNetwork = AsyncMock(return_value=True)
    mock_casambi.applyNetworkAdditions = AsyncMock(side_effect=_apply)
    await config_entry.runtime_data.async_refresh_network()
    await drain(hass)

    # No reload: the existing connection keeps running.
    assert mock_casambi.connect.await_count == 1
    added = sorted(set(_entity_ids(hass, config_entry)) - set(before))
    expected = ["light.unit_2", "number.unit_2_vertical", "scene.test_network_scene_2"]
    if import_groups:
        expected += ["light.test_network_group_2", "number.test_network_group_2"]
    assert added == sorted(expected)
    assert set(before) <= set(_entity_ids(hass, config_entry))
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    assert any((DOMAIN, new_lamp.uuid) in d.identifiers for d in devices)


async def test_empty_additions_keep_running(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
) -> None:
    """A newer revision without new objects neither reloads nor adds."""
    mock_casambi.units = [make_unit(1, [UnitControlType.DIMMER])]
    await _setup(hass, config_entry)
    before = _entity_ids(hass, config_entry)

    mock_casambi.refreshNetwork = AsyncMock(return_value=True)
    mock_casambi.applyNetworkAdditions = AsyncMock(
        return_value=NetworkAdditions([], [], [])
    )
    await config_entry.runtime_data.async_refresh_network()
    await drain(hass)

    assert mock_casambi.connect.await_count == 1
    assert _entity_ids(hass, config_entry) == before


async def test_failed_additions_reload_the_entry(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error while applying the update falls back to a reload."""
    await _setup(hass, config_entry)

    mock_casambi.refreshNetwork = AsyncMock(side_effect=[True, False])
    mock_casambi.applyNetworkAdditions = AsyncMock(side_effect=RuntimeError("bug"))
    await config_entry.runtime_data.async_refresh_network()
    await drain(hass)

    assert config_entry.state is ConfigEntryState.LOADED
    assert mock_casambi.connect.await_count == 2
    assert "Unexpected error while applying the network update" in caplog.text
