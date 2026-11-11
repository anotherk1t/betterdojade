# Local preferences reference

Self-contained reference copy of the local preferences module from the standalone prototype.

- `preferences.js` — localStorage schema, defaults, validation, and theme resolution.
- `ui-preferences.js` — settings dialog behaviour. Imports `./preferences.js`.
- `preferences.test.js` — unit tests for the storage and theme helpers. These run as part of the app test suite.

## Integrating into `src/`

1. Move `preferences.js` to `src/preferences.js`.
2. Move `ui-preferences.js` to `src/ui/preferences.js` and change its import to `../preferences.js`.
3. Add the dialog markup expected by `ui-preferences.js` (`prefs-overlay`, `prefs-open-btn`, `prefs-close-btn`, `prefs-done-btn`, `prefs-reset-btn`, `pref-own-bike-default`, `pref-home`, `pref-work`).
4. Pass `onApply` and `onUsePlace` callbacks from the host app.

Preferences are stored on the device only; there are no accounts.
