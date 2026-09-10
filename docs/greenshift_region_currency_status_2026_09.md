# GreenShift — Region Currency + Carbon/Tariff Representation Fix — Status (2026-09-11)

Scope: `frontend/src/pages/{RegionsPage,CarbonCostPage}.tsx`, new
`frontend/src/utils/currency.ts`, minor type additions to
`frontend/src/types/api.ts` / `frontend/src/api/endpoints.ts` for the tariff
response shapes those two pages already depended on. **No backend files
were changed** — every field needed already existed and was already
correct; this was purely a frontend representation/mapping bug.

## 1. What was audited before writing any code

- `RegionsPage.tsx` / `CarbonCostPage.tsx` (old): both hardcoded `$` for
  every tariff display and used `price_per_kwh_usd` (the USD-normalized
  figure) as if it were the native rate; `CarbonCostPage` additionally
  defaulted a missing currency to `'INR'` in one place and `'USD'` in
  another, and — the one genuine fabricated-fallback bug — hardcoded
  `tariff_price: 0.07` whenever tariff data was missing but carbon data
  wasn't.
- `app/api/routers/ingest.py` (`get_current_tariff`, `get_region_hourly_tariffs`,
  `list_regions_endpoint`) and `app/shared/tariff_service.py`
  (`get_tariff_for_region_and_time`, `get_hourly_tariffs`,
  `get_currency_for_region`): confirmed every tariff response already
  carries **both** a native figure (`effective_price` + `currency`) **and**
  a separately USD-normalized one (`price_per_kwh_usd`) — the bug was
  entirely about which of the two the frontend chose to display, and how
  it labeled it.
- `app/ingest/regional_registry.py`: confirmed India (`IN-TG/IN-GJ/IN-WB/
  IN-PB/IN-HP`, all INR), USA (`US-CA/US-NY/US-TX`, all USD), Sweden (`SE`,
  SEK), and **Australia (`AU-SA-Large`/`AU-SA-Small`, both AUD,
  `Australia/Adelaide`, zone `AU-SA`)** are all genuinely, fully configured
  first-class regions — not something this phase needed to add.
- `data/master_tod_tariff_all_regions.csv`: confirmed real 24-hour tariff
  rows exist for every one of those regions, including both Australian
  regions (verified by direct inspection, not assumption).
- The Electricity Maps carbon pipeline, the scheduler, and the tariff
  backend architecture were read only far enough to confirm they don't
  need to change — none of their logic was touched.

## 2–3. Currency model — IMPLEMENTED

`RegionsPage`'s `EnrichedRegion.tariffUsd` was renamed to `tariffPrice`
(the native `effective_price`) with `tariffCurrency` sourced from the
tariff response's own `currency` (falling back to the region's own
registered currency — never `'USD'`). `CarbonCostPage` no longer reads
`price_per_kwh_usd` anywhere in its UI; the "Local Effective Rate: X INR"
duplicate line is gone — there is now exactly one coherent tariff value per
the brief ("₹38.40 INR/kWh" style), sourced from `effective_price` +
`currency`.

## 4. Carbon data — untouched by design

No change to carbon fetching, formulas, or terminology — "Carbon
Intensity", "gCO₂/kWh", "Source" labels were already currency-independent
and correct. The one pre-existing carbon-pipeline fallback found
(`GET /carbon/current` hardcodes `380.0` when the primary fetch fails) is
**explicitly out of scope** per this phase's own instructions ("do not
change... Electricity Maps integration") — it's already honestly labeled
via `is_fallback: true`, which the frontend already surfaces
("Source: Fallback"). Not modified; noted here for visibility.

## 5–7. Carbon & Tariff page + chart + shared utility — IMPLEMENTED

New `frontend/src/utils/currency.ts`:
- `formatCurrency(value, currencyCode)` — `Intl.NumberFormat` wrapper, "—"
  on missing/invalid input, 2–4 decimal precision (electricity rates like
  `$0.1148/kWh` need more than 2 decimals to stay distinguishable).
- `getCurrencySymbol(currencyCode)` — derives the display symbol from Intl
  rather than a country switch.
- `formatRate(value, currencyCode, unit)` — the full "₹38.40 INR/kWh" form.
- `currencyRateUnitLabel(currencyCode, unit)` — the compact "₹/kWh" form for
  chart axes/legends.

**Deliberate implementation choice, verified in this exact environment:**
all formatting uses a **fixed base locale (`'en-US'`)**, not the viewer's
own locale (the brief's own example used `Intl.NumberFormat(undefined, …)`).
Verified directly in Node: `Intl.NumberFormat('en-AU', {currency:'AUD'})`
renders AUD as a bare `"$"` (Australia's own local symbol), which would
silently defeat the entire "never show AUD as $" requirement for any
Australian viewer. `'en-US'` reliably renders `AUD → "A$"`, `USD → "$"`,
`INR → "₹"` — confirmed against Node's actual ICU data before relying on
it, not assumed.

`CarbonCostPage`'s chart: `unit=" $"` on the right `YAxis` → a
`tickFormatter` that calls `formatRate` (so ticks read "A$0.28 AUD/kWh",
not a bare number with a trailing unit); the `<Tooltip>` gained a
`formatter` that applies `formatRate` only to the tariff series; both
`Area` series' `name` and the axis `label` are now computed from the
selected region's real currency (`Tariff (₹/kWh)` / `Tariff (A$/kWh)` /
etc.) — since Recharts' `<Legend>` renders each series' `name` verbatim,
fixing `name` fixes the legend for free. The `tariff_price: 0.07` fabricated
fallback is deleted outright — when tariff data is genuinely unavailable
for an hour, that point's `tariff_price` is simply `undefined` and the
tariff series has a gap there rather than a lie.

## 8. Australia — verified first-class, not just "can format AUD"

Per the brief's own final rule, this is not claimed on the strength of the
frontend alone. **Verified end-to-end against the real, running backend**
(§10 below): `AU-SA-Large` and `AU-SA-Small` both return real
`country: "Australia"`, `currency: "AUD"`, `timezone: "Australia/Adelaide"`,
`electricity_maps_zone: "AU-SA"`, live (non-fallback) carbon readings, and
real 24-hour tariff curves from the master dataset. One genuine data
characteristic worth flagging: `AU-SA-Large`'s "Demand" tariff plan has a
real `Effective_price` of `0.0` for **all 24 hours** in the dataset (demand
tariffs bill for peak kW capacity, not per-kWh energy, so a $0/kWh energy
component is a plausible real value for this plan type — confirmed by
reading the raw CSV rows directly, not assumed). The frontend correctly
displays this as `"A$0.00 AUD/kWh"` — a real zero, distinct from the "—"
shown when data is genuinely absent. `AU-SA-Small`'s ToD plan has real
non-zero rates (e.g. `A$0.09 AUD/kWh`), confirmed live.

## 9. Scheduler / region×time compatibility

Not touched. No AUD/INR→USD conversion was added anywhere in the display
path; `price_per_kwh_usd` remains available in the typed response shape for
any future cross-region comparison need, it's just no longer what's shown
as "the" tariff.

## 10. Real, live E2E verification (not mocked)

Per the brief's explicit instruction not to use mocked responses for this
verification: started the actual FastAPI backend (`uvicorn`, fresh SQLite
dev DB, real Alembic migrations, real dev-seeded `admin`/`admin123`
PLATFORM_ADMIN account — no test doubles) and the actual Vite dev server,
then drove a real Chromium browser (Playwright) through a real login and
both pages.

**Direct backend confirmation** (`curl`, unmocked):
- `GET /api/v1/tariffs/IN-TG/current` → `currency: "INR"`, `effective_price: 7.15`
- `GET /api/v1/tariffs/US-CA/current` → `currency: "USD"`, `effective_price: 0.11482`
- `GET /api/v1/tariffs/AU-SA-Small/current` → `currency: "AUD"`, `effective_price: 0.09`
- `GET /api/v1/carbon/current?region=AU-SA-Small` → `carbon_gco2_kwh: 29.0`, `is_fallback: false` (genuinely live, not a fallback reading)

**Live browser confirmation** (screenshots + full DOM text captured):
- **Regions & Capacity** — all 11 real configured regions rendered
  correctly: 5 India cards all `₹…INR/kWh`; 3 USA cards all `$…USD/kWh`;
  Sweden `SEK 0.034 SEK/kWh` (no dedicated symbol — correctly falls back to
  the code, not a bug); **`South Australia (Large)`: `A$0.00 AUD/kWh`** and
  **`South Australia (Small)`: `A$0.09 AUD/kWh`** — matching the direct
  curl values exactly, never a bare `$`.
- **Carbon & Tariffs**, switching the region selector live in the browser:
  - India (default, IN-TG): `₹7.15 INR/kWh`; chart legend `Tariff (₹/kWh)`;
    Y-axis ticks `₹0.00 INR/kWh` … `₹12.00 INR/kWh`.
  - USA (US-CA): `$0.1148 USD/kWh`; chart legend `Tariff ($/kWh)`; Y-axis
    ticks in `$`.
  - Australia (AU-SA-Large): Grid Zone `AU-SA`, Currency `AUD`; live
    reading `A$0.00 AUD/kWh`; chart legend `Tariff (A$/kWh)`; Y-axis ticks
    `A$0.00 AUD/kWh` … `A$4.00 AUD/kWh` — never a bare `$` anywhere on the
    page.
- No console errors, no page errors, during any of the above.

## 11. Tests

**Before:** 291/291 was not yet the baseline for this phase — the prior
verified baseline (232 approvals-phase count aside) carried forward to
**260/260** after Phase 5. Neither `RegionsPage` nor `CarbonCostPage` had
any tests before this phase.

**After: 291/291 passing** (260 + 31 new): `utils/currency.test.ts` (15 —
INR/USD/AUD formatting, a future ISO currency needing no code change,
missing/invalid currency and value handling, symbol derivation, the full
rate/compact-label forms), `RegionsPage.test.tsx` (7 — loading state,
India/USA/Australia real native tariffs with an explicit "never a bare $
for AUD" assertion, honest unavailable states for a failed tariff or
carbon fetch, and a working error+Retry), `CarbonCostPage.test.tsx` (9 —
India/USA/Australia chart series names and live readings, the Y-axis label
and tick formatter and tooltip formatter all dynamically deriving from the
selected region's currency, no fabricated `0.07` tariff fallback, a real
error state instead of a zeroed reading, and no USD assumption before any
region has loaded). Recharts' `ResponsiveContainer` doesn't lay out in
jsdom (confirmed directly — even a minimal repro renders nothing with
percentage dimensions), so `CarbonCostPage.test.tsx` mocks `recharts` at
the module boundary to inspect the *props this page computes and passes to
it* (series names, tick/tooltip formatter output, axis label) rather than
asserting on the third-party library's own SVG rendering — this is deliberately in
addition to, not instead of, the real-browser verification in §10, which
does exercise the actual rendered chart.

## 12. Build result

`npm run build` (tsc + vite build) — **passes**, no type errors.

## 13. Regression check

Full frontend suite (291/291) and a fresh `npm run build` both pass with no
changes to any other page. Nothing in Authentication, Dashboard, Workloads,
Submit Workload, Scheduling, Approvals, or their backend endpoints was
touched — this phase's diff is confined to the two named pages, the new
currency utility, and additive type declarations for response shapes those
pages already consumed.

## 14. Backend data gaps

**None found that block this phase's scope.** Everything India/USA/
Australia needed already existed correctly in the backend. The only
pre-existing item of note (§4) is the `/carbon/current` hardcoded `380.0`
fallback, which is out of scope for a currency-representation fix and is
already honestly labeled `is_fallback: true`.
