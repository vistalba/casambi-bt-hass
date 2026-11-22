"""Tests for the reconnect handling of the Casambi Bluetooth integration."""

# ruff: noqa: SLF001

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from CasambiBt import Casambi
from CasambiBt._client import CasambiClientEvolution
from CasambiBt._constants import ConnectionState
from CasambiBt.errors import BluetoothError, ProtocolError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.casambi_bt import CasambiApi
from custom_components.casambi_bt.const import DOMAIN
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant

ADDRESS = "00:11:22:33:44:55"


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ADDRESS: ADDRESS, CONF_PASSWORD: "secret"},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def ble_device():
    """Pretend that the network is always visible to HA."""
    with patch(
        "custom_components.casambi_bt.bluetooth.async_ble_device_from_address",
        return_value=MagicMock(address=ADDRESS),
    ):
        yield


@pytest.fixture
def api(hass: HomeAssistant, entry: MockConfigEntry) -> CasambiApi:
    """Return a CasambiApi wrapping a real Casambi object without bluetooth."""
    with patch("custom_components.casambi_bt.get_async_client"):
        api = CasambiApi(hass, entry, ADDRESS, "secret")

    casa: Casambi = api._casa
    network = MagicMock(protocolVersion=10, _networkRevision=1, units=[])
    casa._casaNetwork = network
    casa.connect_attempts = 0

    async def connect_client(_device) -> None:
        casa.connect_attempts += 1
        client = CasambiClientEvolution(
            ADDRESS, MagicMock(), casa._disconnectCallback, network
        )
        client._connectionState = ConnectionState.AUTHENTICATED
        casa._casaClient = client

    casa._connectClient = connect_client
    casa.registerDisconnectCallback(api._casa_disconnect)
    return api


async def _connect(api: CasambiApi) -> None:
    await api._casa._connectClient(None)
    api._casa.connect_attempts = 0
    api._link_up = True


async def test_reconnect_after_disconnect_callback(api: CasambiApi) -> None:
    """A disconnect reported by bleak must lead to a real reconnect.

    The library runs the disconnect callback while it still reports itself as
    connected and HA starts background tasks eagerly.
    """
    await _connect(api)
    status_updates = MagicMock()
    api.register_connection_updates(status_updates)

    api._casa._casaClient._on_disconnect(MagicMock())
    assert not api.available

    await asyncio.wait_for(api._reconnect_task, 5)

    assert api._casa.connect_attempts == 1
    assert api.available
    assert status_updates.call_count == 2


@pytest.mark.parametrize("error", [TimeoutError, BluetoothError, ProtocolError])
async def test_reconnect_keeps_retrying(
    api: CasambiApi, error: type[Exception]
) -> None:
    """Transient errors must not end the reconnect loop."""
    await _connect(api)
    real_reconnect = api._casa.reconnect
    errors = [error(), error(), error()]

    async def reconnect(device) -> None:
        if errors:
            raise errors.pop()
        await real_reconnect(device)

    api._casa.reconnect = AsyncMock(side_effect=reconnect)

    api._casa._casaClient._on_disconnect(MagicMock())
    with patch("custom_components.casambi_bt.asyncio.sleep", AsyncMock()):
        await asyncio.wait_for(api._reconnect_task, 5)

    assert api._casa.reconnect.await_count == 4
    assert api.available


async def test_write_timeout_schedules_reconnect(api: CasambiApi) -> None:
    """A timeout during a write must trigger a reconnect instead of failing."""
    await _connect(api)
    api._casa.turnOn = AsyncMock(side_effect=TimeoutError)

    with patch.object(api, "_schedule_reconnect") as schedule_reconnect:
        await api.casa.turnOn(None)

    schedule_reconnect.assert_called_once()
