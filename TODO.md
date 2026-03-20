From earlier in our conversation, the remaining recommended enhancements in priority order:

**Reliability**
1. **DONE** **Re-auth flow** — `async_step_reauth()` in `config_flow.py`. When a key is revoked HA surfaces a persistent notification rather than silently failing. Highest priority missing feature.
2. **DONE** **Retry with exponential backoff** — transient network blips silently drop symbols from that update cycle. A backoff decorator on `get_quote()` in `api.py` would handle these without hammering the API.
3. **DONE** **Partial update failure handling** — carry forward last known value for symbols that fail in a given cycle rather than dropping them from results entirely.

**Observability**
4. **`async_get_config_entry_diagnostics()`** — one function in `__init__.py`, adds a **Download Diagnostics** button in the UI that dumps coordinator state with the API key redacted. Very low effort.
5. **DONE** **Rate limiter sensor** — expose calls used in current minute/burst windows as a diagnostic sensor. Useful with large symbol lists.
6. **DONE** **Stale data indicator** — add `data_as_of` attribute to each quote sensor using the Finnhub `t` timestamp field. Surfaces when a ticker is returning stale data.

**User experience**
7. **Currency support** — fetch currency from `/stock/profile2` once at setup and use it as `native_unit_of_measurement` instead of hardcoded USD. Needed for LSE, TSX, and other non-USD symbols.
8. **Symbol validation in config flow** — call `get_quote()` for the first symbol during setup to catch ticker typos before the entry is created.
9. **Change percent as its own sensor** — `sensor.market_spy_change_pct` with `SensorStateClass.MEASUREMENT` so it appears in HA statistics and can drive dashboard conditional formatting.

**Integration maturity**
10. **`hassfest` compliance check** — run `python3 -m script.hassfest` to validate manifest, translations, and code quality rules before publishing.
11. **`CHANGELOG.md`** — displayed by HACS in the integration detail page.
12. **`hacs.json`** — add `homeassistant` minimum version field.

The ones already implemented are: coordinator health sensor, device grouping, market hours scheduling, holiday API check, background startup fetch, and the `DeviceEntryType` fix.