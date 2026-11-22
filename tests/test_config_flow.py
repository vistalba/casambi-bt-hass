"""Tests for the cache handling and error reporting of the config flow."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

from CasambiBt.errors import AuthenticationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.casambi_bt import async_remove_entry, get_cache_dir
from custom_components.casambi_bt.config_flow import _validate_input
from custom_components.casambi_bt.const import DOMAIN
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant

ADDRESS = "00:11:22:AA:BB:CC"
CACHE_UUID = "001122aabbcc"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components."""
    return


@pytest.fixture
def casa():
    """Return a mocked Casambi object used by the config flow."""
    with (
        patch("custom_components.casambi_bt.config_flow.Casambi") as casambi_cls,
        patch("custom_components.casambi_bt.config_flow.get_async_client"),
        patch(
            "custom_components.casambi_bt.config_flow.async_ble_device_from_address",
            return_value=MagicMock(address=ADDRESS),
        ),
    ):
        casa = casambi_cls.return_value
        casa.invalidateCache = AsyncMock()
        casa.connect = AsyncMock()
        casa.disconnect = AsyncMock()
        casa.networkName = "Home"
        yield casa


async def test_validate_input_invalidates_cache_of_network(
    hass: HomeAssistant, casa: MagicMock
) -> None:
    """The cache key must match the one CasambiBt uses for the network."""
    await _validate_input(hass, {CONF_ADDRESS: ADDRESS, CONF_PASSWORD: "secret"})

    casa.invalidateCache.assert_awaited_once_with(CACHE_UUID)


async def test_validate_input_auth_error_is_logged(
    hass: HomeAssistant, casa: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """The reason for an authentication failure must end up in the log."""
    casa.connect.side_effect = AuthenticationError("Login failed: 401")
    with (
        patch(
            "custom_components.casambi_bt.config_flow.async_scanner_count",
            return_value=1,
        ),
        caplog.at_level(logging.WARNING),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_ADDRESS: ADDRESS, CONF_PASSWORD: "wrong"},
        )

    assert result["errors"] == {"base": "invalid_auth"}
    assert "Login failed: 401" in caplog.text


async def test_remove_entry_deletes_cache(hass: HomeAssistant, tmp_path) -> None:
    """Removing the integration must drop the cached session and keys."""
    hass.config.config_dir = str(tmp_path)
    cache_entry = get_cache_dir(hass) / CACHE_UUID
    cache_entry.mkdir(parents=True)
    (cache_entry / "session.pck").write_bytes(b"")
    other_entry = get_cache_dir(hass) / "ffffffffffff"
    other_entry.mkdir()
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_ADDRESS: ADDRESS, CONF_PASSWORD: "secret"}
    )

    await async_remove_entry(hass, entry)

    assert not cache_entry.exists()
    assert other_entry.exists()
