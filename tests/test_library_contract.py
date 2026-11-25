"""Contract tests between the integration and the real casambi-bt library.

The integration runs against the real library. Only the Casambi cloud
(http transport) and the bluetooth connection are replaced, so the cache,
the offline handling, the error types and the backup format are exercised
as in production.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from CasambiBt import Casambi
from CasambiBt._client import CasambiClientEvolution
from CasambiBt._constants import ConnectionState
import httpx
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.casambi_bt.const import (
    CONF_IMPORT_GROUPS,
    CONF_OFFLINE_MODE,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import TEST_ADDRESS, TEST_UUID, drain

NETWORK_ID = "net-1"
PASSWORD = "right-password"

# The cloud fixture replaces the bluetooth connection of the library. Tests
# of the bluetooth handling put the real implementation back.
_REAL_CONNECT_CLIENT = Casambi._connectClient  # noqa: SLF001
FIXTURE = {
    "id": 42,
    "model": "Spot",
    "vendor": "Acme",
    "mode": "Dim",
    "stateLength": 1,
    "controls": [
        {"type": "dimmer", "offset": 0, "length": 8, "default": 0, "readonly": False}
    ],
}


def _network(revision: int, units: int) -> dict[str, Any]:
    return {
        "status": "OK",
        "network": {
            "name": "Home",
            "revision": revision,
            "protocolVersion": 10,
            "keyStore": {
                "keys": [{"id": 1, "type": 1, "role": 3, "name": "k", "key": "00" * 16}]
            },
            "units": [
                {
                    "type": 42,
                    "deviceID": i,
                    "uuid": f"unit-{i}",
                    "address": "a",
                    "name": f"Lamp {i}",
                    "firmware": 1,
                }
                for i in range(1, units + 1)
            ],
            "grid": {"cells": []},
            "scenes": [],
        },
    }


class FakeCloud:
    """The Casambi cloud as far as casambi-bt uses it."""

    def __init__(self) -> None:
        """Start online with a network of one unit."""
        self.offline = False
        self.session_status = 200
        self.network = _network(revision=1, units=1)
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Answer a request of the library."""
        self.requests.append(request.url.path)
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        path = request.url.path
        if path == f"/network/uuid/{TEST_UUID}":
            return httpx.Response(200, json={"id": NETWORK_ID})
        if path == f"/network/{NETWORK_ID}/session":
            if self.session_status != 200:
                return httpx.Response(self.session_status, text="error")
            if json.loads(request.content)["password"] != PASSWORD:
                return httpx.Response(401, text="wrong password")
            expires = (datetime.now(UTC) + timedelta(days=7)).timestamp() * 1000
            return httpx.Response(
                200,
                json={
                    "session": "session",
                    "network": NETWORK_ID,
                    "manager": True,
                    "keyID": 1,
                    "expires": expires,
                },
            )
        if path == f"/network/{NETWORK_ID}/":
            revision = json.loads(request.content)["revision"]
            if revision == self.network["network"]["revision"]:
                return httpx.Response(200, json={"status": "UPTODATE"})
            return httpx.Response(200, json=self.network)
        if path == "/fixture/42":
            return httpx.Response(200, json=FIXTURE)
        return httpx.Response(404)


@pytest.fixture
def cloud() -> Generator[FakeCloud]:
    """Route the library to a fake cloud and replace the bluetooth link."""
    fake = FakeCloud()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    device = BLEDevice(TEST_ADDRESS, "Casambi", None)
    with (
        patch("custom_components.casambi_bt.get_async_client", return_value=client),
        patch(
            "custom_components.casambi_bt.config_flow.get_async_client",
            return_value=client,
        ),
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=device,
        ),
        patch(
            "custom_components.casambi_bt.config_flow.async_ble_device_from_address",
            return_value=device,
        ),
        patch(
            "homeassistant.components.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch.object(Casambi, "_connectClient", AsyncMock()),
    ):
        yield fake


@pytest.fixture
def entry(hass: HomeAssistant, tmp_path) -> MockConfigEntry:
    """A config entry with the cache in a temporary config dir."""
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={CONF_ADDRESS: TEST_ADDRESS, CONF_PASSWORD: PASSWORD},
        options={CONF_IMPORT_GROUPS: True, CONF_OFFLINE_MODE: False},
        unique_id=TEST_ADDRESS,
        version=2,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await drain(hass)


def _unit_devices(hass: HomeAssistant, entry: MockConfigEntry) -> list[str]:
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    return sorted(
        d.name or ""
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if d.model != "Network"
    )


pytestmark = pytest.mark.usefixtures("enable_bluetooth")


async def test_restart_without_cloud(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """After one online start the network starts without the cloud."""
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert _unit_devices(hass, entry) == ["Lamp 1"]

    await hass.config_entries.async_unload(entry.entry_id)
    cloud.offline = True
    cloud.requests.clear()

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert _unit_devices(hass, entry) == ["Lamp 1"]
    # Only the background refresh tried the cloud.
    assert not hass.config_entries.flow.async_progress()


async def test_cloud_outage_does_not_ask_for_the_password(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """A cloud answering 503 must not start reauth (it used to)."""
    cloud.session_status = 503

    await _setup(hass, entry)

    # Without a cache there is nothing to start from yet.
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_rejected_password_asks_for_the_password(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """A wrong password is reported as such and starts reauth."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_PASSWORD: "wrong"}
    )

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_new_units_are_added_by_the_refresh(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """A unit added in the app appears after the next refresh.

    The entry isn't reloaded for that (rule dynamic-devices), so the
    bluetooth connection stays up.
    """
    await _setup(hass, entry)
    assert _unit_devices(hass, entry) == ["Lamp 1"]
    connect_client: AsyncMock = Casambi._connectClient  # type: ignore[assignment]  # noqa: SLF001
    assert connect_client.await_count == 1

    cloud.network = _network(revision=2, units=2)
    await entry.runtime_data.async_refresh_network()
    await drain(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert _unit_devices(hass, entry) == ["Lamp 1", "Lamp 2"]
    assert connect_client.await_count == 1


async def test_removed_units_reload_the_entry(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """Other changes than additions are applied by reloading the entry."""
    cloud.network = _network(revision=1, units=2)
    await _setup(hass, entry)
    assert _unit_devices(hass, entry) == ["Lamp 1", "Lamp 2"]
    connect_client: AsyncMock = Casambi._connectClient  # type: ignore[assignment]  # noqa: SLF001

    cloud.network = _network(revision=2, units=1)
    await entry.runtime_data.async_refresh_network()
    await drain(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert connect_client.await_count == 2
    assert _unit_devices(hass, entry) == ["Lamp 1"]


async def test_offline_backup_roundtrip(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """A network is set up again from a backup without any cloud access."""
    await _setup(hass, entry)
    backup = await hass.services.async_call(
        DOMAIN,
        "export_offline_backup",
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert backup["network"]["network"]["keyStore"]["keys"]

    # Removing the entry deletes the cache; the cloud is gone for good.
    await hass.config_entries.async_remove(entry.entry_id)
    await drain(hass)
    cloud.offline = True
    cloud.requests.clear()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "backup"}
    )
    # The backup survives the trip through a password manager as text.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"backup": json.dumps(backup, indent=2), CONF_IMPORT_GROUPS: True},
    )
    await drain(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    restored = result["result"]
    assert restored.state is ConfigEntryState.LOADED
    assert _unit_devices(hass, restored) == ["Lamp 1"]
    # Restoring a backup defaults to the offline mode: no cloud access at all.
    assert cloud.requests == []


async def test_offline_mode_never_contacts_the_cloud(
    hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry
) -> None:
    """In offline mode the cloud isn't used even when it is reachable."""
    await _setup(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_OFFLINE_MODE: True}
    )
    cloud.requests.clear()
    cloud.network = _network(revision=2, units=2)

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert cloud.requests == []
    assert _unit_devices(hass, entry) == ["Lamp 1"]


class FakeLink:
    """Bluetooth links of the real casambi-bt client with a fake GATT client.

    Only the BLE transport and the handshake are replaced. The connection
    state machine, the error handling and the reconnect logic of the
    library run as in production.
    """

    def __init__(self) -> None:
        """Start without any link."""
        self.gatts: list[MagicMock] = []

    def new_gatt(self) -> MagicMock:
        """Return the GATT client of a new, connected link."""
        gatt = MagicMock()
        gatt.is_connected = True
        gatt.write_gatt_char = AsyncMock()
        gatt.disconnect = AsyncMock()
        self.gatts.append(gatt)
        return gatt


@pytest.fixture
def link(cloud: FakeCloud) -> Generator[FakeLink]:
    """Connect the real library client through a fake GATT client."""
    fake = FakeLink()

    async def connect(client: CasambiClientEvolution) -> None:
        client._gattClient = fake.new_gatt()  # noqa: SLF001
        client._connectionState = ConnectionState.CONNECTED  # noqa: SLF001

    async def exchange_key(client: CasambiClientEvolution, retries: int = 2) -> None:
        client._nonce = bytes(16)  # noqa: SLF001
        client._encryptor = MagicMock()  # noqa: SLF001
        client._encryptor.encryptThenMac.return_value = b"encrypted"  # noqa: SLF001
        client._connectionState = ConnectionState.KEY_EXCHANGED  # noqa: SLF001

    async def authenticate(client: CasambiClientEvolution) -> None:
        client._connectionState = ConnectionState.AUTHENTICATED  # noqa: SLF001

    with (
        patch.object(Casambi, "_connectClient", _REAL_CONNECT_CLIENT),
        patch.object(CasambiClientEvolution, "connect", connect),
        patch.object(CasambiClientEvolution, "exchangeKey", exchange_key),
        patch.object(CasambiClientEvolution, "authenticate", authenticate),
    ):
        yield fake


def _light_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    return next(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "light" and "-unit-" in e.unique_id
    )


async def test_lost_link_is_detected_on_write(
    hass: HomeAssistant, link: FakeLink, entry: MockConfigEntry
) -> None:
    """A write on a link that dropped without a disconnect callback reconnects.

    ESPHome proxies report such a write as "<device> is not connected".
    The library must detect the lost link, tear the old client down and
    reconnect, instead of keeping a dead connection that it still reports
    as connected.
    """
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert len(link.gatts) == 1
    # Units are online once the network reported their state.
    api = entry.runtime_data
    for unit in api.casa.units:
        unit._online = True  # noqa: SLF001
        api._unit_changed_handler(unit)  # noqa: SLF001
    await hass.async_block_till_done()
    dead = link.gatts[0]
    dead.is_connected = False
    dead.write_gatt_char.side_effect = BleakError(
        f"Casambi Network - {TEST_ADDRESS} is not connected"
    )

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": _light_entity_id(hass, entry)},
        blocking=True,
    )

    # The old client was disconnected although its link was already down,
    # so no stale state (e.g. BlueZ notify sessions) is left behind.
    dead.disconnect.assert_awaited()
    assert len(link.gatts) == 2
    link.gatts[1].write_gatt_char.assert_awaited_once()
    assert api.available


async def test_disconnect_callback_reconnects(
    hass: HomeAssistant, link: FakeLink, entry: MockConfigEntry
) -> None:
    """A disconnect reported by bleak leads to a new connection."""
    await _setup(hass, entry)
    api = entry.runtime_data
    client = api.casa._casaClient  # noqa: SLF001
    link.gatts[0].is_connected = False

    client._on_disconnect(link.gatts[0])  # noqa: SLF001
    assert not api.available
    await drain(hass)

    link.gatts[0].disconnect.assert_awaited()
    assert len(link.gatts) == 2
    assert api.available
