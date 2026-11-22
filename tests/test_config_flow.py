"""Tests for the config flow input validation."""

from unittest.mock import AsyncMock

from custom_components.casambi_bt.config_flow import _validate_input
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .conftest import TEST_ADDRESS, TEST_UUID, MockCasambi


async def test_validate_input_normalizes_cache_uuid(
    hass: HomeAssistant,
    mock_casambi: MockCasambi,
    mock_bluetooth: AsyncMock,
) -> None:
    """The cache must be invalidated under the normalized uuid.

    The library names its cache directory after the mac without colons in
    lower case. Passing the raw address made invalidation a silent no-op,
    so the flow silently reused a cached cloud session and never validated
    the entered password.
    """
    mock_casambi.networkName = "Test Network"

    info = await _validate_input(
        hass,
        {CONF_ADDRESS: TEST_ADDRESS, CONF_PASSWORD: "secret-password"},
    )

    assert info == {"title": "Test Network", "id": TEST_ADDRESS}
    mock_casambi.invalidateCache.assert_awaited_once_with(TEST_UUID)
    mock_casambi.connect.assert_awaited_once()
