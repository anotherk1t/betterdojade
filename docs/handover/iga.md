# Iga — Frontend redesign handover

**Branch:** `iga/frontend-redesign`
**Goal:** port the standalone design prototype into the main app as a light, responsive redesign while keeping the existing routing and data wiring.

## References

- Prototype screenshots: `docs/design/prototype/*.png` — desktop light/dark, mobile light/dark, route detail, all routes, navigation, and transit mode.
- Preferences screenshots: `docs/design/preferences/*.jpg` — light/dark main views, settings dialogs, and mobile layout.
- Preferences reference module: `prototype/preferences/` (see its `README.md`).
- Baseline for comparison: the current UI and the screenshots above.
- The standalone prototype is a design reference, not production code. Do not merge it wholesale.

The prototype screenshots show a neutral `Preview` label and sample data marked as `Demo data` / `sample availability`. Keep that honesty in the production port.

## Tasks

1. Add design tokens to `src/style.css`: light theme default, dark theme optional, one accent colour, consistent radii and shadows.
2. Restructure `index.html` and the sidebar to match the references while preserving existing IDs and JavaScript hooks.
3. Port the route cards, mode tabs (MEVO / Walk / Transit), MEVO markers, route detail, and mobile layout.
4. Integrate the local preferences module from `prototype/preferences/` (theme, default mode, own bike, home and work).
5. Remove unverified freshness claims. Keep sample or mocked data clearly labelled. Clean up emoji icons, gradient/glow overload, and generic copy.
6. Add a small visual smoke check and screenshots.

## Acceptance criteria

- Light, dark, and auto themes work; light is the default.
- Responsive down to 360 px.
- Real route and data flow still works; no mock data in production paths.
- Sample or mocked data is labelled as such; no unverified freshness claims.
- `npm run test:run` and `npm run build` pass.
- No console errors.

## Suggested first commits

1. `feat(ui): add light/dark design tokens`
2. `feat(ui): restructure sidebar and route cards`
3. `feat(ui): responsive mobile layout`
4. `feat(ui): integrate local preferences`
5. `test(ui): add visual smoke check`
