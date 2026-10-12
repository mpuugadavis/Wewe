# WEWE brand and responsive storefront

The frontend now uses an outlined SVG WEWE wordmark and connected W symbol in the established #6C3DF4 purple identity. Purple, reversed white and single-colour ink variants support the website, favicon, apparel, packaging and print. See `frontend/assets/brand/README.md` for sizing and production guidance and `frontend/assets/brand/preview.html` for the brand sheet.

The active header, footer, dashboard and sign-in form use proportionally sized SVG assets. Historical backup HTML and the legacy raster logo remain available for reference.

The homepage pairs an editorial food/style/study grid with clear shopping and retailer actions, a campus introduction and the existing live categories, catalog, deals, recently viewed products and retailers. Responsive rules live in `frontend/brand.css`, loaded after the existing stylesheet to resolve conflicting legacy breakpoints. Header/search, cards, pricing, rails, basket, checkout, mobile safe areas and workspace layouts adapt to narrow screens. Dialog keyboard focus, accessible titles and focus restoration live in `frontend/brand-ui.js`.

## Integration preservation

Backend application code, migrations, Docker configuration, environment examples, OpenRouteService and PawaPay adapters are unchanged. The only change inside `frontend/app.js` is the sign-in heading/logo markup. API URLs, authentication, route-distance ownership, checkout totals, mobile-money methods and order/payment idempotency remain unchanged.

Verification uncovered stale backend test fixtures. The OpenRouteService HTTP mocks now return themselves from `__enter__`, matching the adapter's existing context-manager use. The production configuration fixture supplies HTTPS PawaPay callbacks and a LIVE environment, as required by the existing validator. These are test-only changes; the application retains its original sandbox defaults.

## Verification

- JavaScript syntax checks: `app.js`, `retailer-media.js`, `brand-ui.js`, `responsive.browser.cjs` pass.
- Existing `node frontend/smoke.js` passes.
- All seven SVG assets parse as XML and the active browser logos load with their original aspect ratio.
- Backend Python compilation and package wheel build pass.
- Routing, payment schema, cart and production configuration regression selection: **37 passed** (dependency deprecation warnings only).
- Installed Edge/Chromium: **11 responsive journeys passed**, widths 320, 360, 390, 540, 680, 768, 900, 1024, 1280 and 1440 at 900px height, plus 844 × 390 landscape.
- WebKit 18.4: **3 responsive journeys passed**, widths 390, 768 and 1440 at 900px height. This caught and resolved native destination-select overflow and Safari-style click focus restoration.
- Firefox 135: **3 responsive journeys passed**, widths 390, 768 and 1440 at 900px height. SVGs now include explicit intrinsic dimensions as well as their scalable viewBox, resolving Firefox's zero intrinsic-size behavior.
- Additional 390px and 1440px journeys with actual photography and web fonts pass; desktop/mobile previews were visually inspected.

The browser journeys cover search, sorting, empty/error/retry states, logo loading and proportions, dialog focus and Escape, basket quantities, delivery and pickup quotes, both mobile-money payloads, phone normalization, order/payment idempotency, customer workspace layout and horizontal overflow. All API calls use fixtures; no real orders or payments are created. Third-party map CDNs are intentionally unavailable in these tests to verify that destination selection and server-authoritative quotes remain usable when the map cannot load. Deterministic screenshots use image/font substitutes; the optional `WEWE_TEST_PHOTOS=live` mode captures actual editorial photography and fonts.

The frontend is static HTML/CSS/JavaScript and has no bundler/build command. `.github/workflows/phase-5.yml` retains the original syntax/smoke checks and adds Chromium, Firefox, WebKit and backend regressions. Browser tooling is pinned to Playwright 1.51.1. `WEWE_TEST_ENGINE`, `WEWE_TEST_CHANNEL`, `WEWE_TEST_WIDTHS` and `WEWE_TEST_PREVIEW=viewport` support targeted local verification without changing application behavior.

GitHub Actions on the initial PR revision stopped before running any steps and exposed no usable job logs. These runs are not evidence of a code-test failure; CI completion remains an external limitation. Local verification used an approved shell because the sandbox launcher encounters a BitLocker-locked drive.
