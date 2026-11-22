# Changelog

## 0.3.0-beta10

Requires Home Assistant 2026.8 or newer.

### Fixes

- **Groups of different lights were not added at all**, e.g. dimmers together with color lights. Home Assistant refused their combined color modes; they are now reduced to a valid set. Units with only a white channel are added as on/off lights instead of being dropped.
- **Setting only a color on an off light left it off.** Units now switch on and restore their last level; off groups no longer get a level of 0 synced after the color.
- **Reauth and reconfigure accepted a wrong password** while a cached cloud session was valid or the cloud was unreachable. The password is now always checked by the Casambi cloud, without touching the cache of the running network.
- **No more login flood after rejected credentials:** every bluetooth advertisement triggered a new failing login until the reauth was done.
- **Cloud rate limits (HTTP 403) are no longer treated as a wrong password:** setup retries later, the reconnect continues with backoff and the dialogs show a dedicated message.
- Units with only a xy color control are added as lights.
- The validation connection of the dialogs is always closed, even when cancelled (bluetooth proxies only have a few connection slots).
- A failing cache migration no longer aborts the setup.
- Values a light rejects fail the action with a clear message.

### Security

- Diagnostics no longer contain the bluetooth address of discovered networks (`discovery_keys`).
- The cache with cloud session and network keys is only accessible to the Home Assistant user.
- Cache paths are only derived from valid mac addresses; removing an entry can no longer delete files outside the cache.
- The cloud's response body is no longer logged on failed logins.
- The README no longer asks to post the library debug log, which contains the network keys.

### Internal

- Commands are sent through a typed method instead of a dynamic proxy, so mypy checks them.
- Entities no longer write private fields of library objects.
- Scene activations are logged at debug level; CI uses actions/checkout v5.
- 125 tests (99 % coverage), including tests against the real login code of casambi-bt.

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
