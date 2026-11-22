# Changelog

## 0.3.0-beta9

Requires Home Assistant 2026.8 or newer.

### Fixes

- The reconnect loop no longer dies on authentication, protocol or unexpected errors. Rejected credentials now start the re-authentication flow; other errors are retried with the maximum backoff instead of leaving the integration unavailable until a manual reload.
- Unit entities could be missing when the light or number platform was set up before the binary sensor platform, because the network device didn't exist yet. The network device is now registered before the platforms.
- Unloading no longer disconnects when a platform failed to unload.
- Unexpected errors during setup are retried instead of failing the entry permanently.
- Light groups of RGBW units without color values no longer crash.
- Lights with several color controls report the color mode of the active color source instead of always RGB.
- Light groups apply `xy_color` instead of ignoring it.
- Actions fail with a clear error for every library error, not only bluetooth errors.
- Entity callbacks are always removed, also when adding an entity fails.
- Adding an already configured network aborts instead of overwriting the existing entry.

### Changes

- **The vertical number of units is now called "Vertical"** instead of "Illuminance" and no longer has the illuminance device class. Entity ids stay the same.
- **"Import groups" moved to the integration options** (*Configure*); existing entries are migrated automatically.
- New *Reconfigure* flow to change the network password.
- Discovered networks only ask for the password.
- A repair issue explains when no connectable bluetooth adapter or proxy is available.
- Devices of units deleted in the Casambi app are removed on start or reload.
- Connection loss and recovery are logged once at info level.
- Translated entity names, exceptions and form descriptions; complete German and Dutch translations.

### Internal

- Typed `ConfigEntry.runtime_data`, `entity.py`, frozen entity descriptions, `PARALLEL_UPDATES`, icon translations and `quality_scale.yaml`.
- Strict mypy, test coverage of 98 % (89 tests), HACS validation and coverage threshold in CI.
