class FinnhubLevelsCard extends HTMLElement {
  static getStubConfig() {
    return {
      symbols: ["SPY", "QQQ", "AAPL"],
      title: "Price levels",
      show_price: true,
    };
  }

  static getConfigElement() {
    return document.createElement("div");
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });

    this._hass = null;
    this._config = {
      symbols: ["SPY", "QQQ", "AAPL"],
      title: "Price levels",
      show_price: true,
    };

    this._levels = {};
    this._alertsEnabled = {};
    this._saving = false;
    this._saved = false;
    this._dirty = false;
    this._error = null;
    this._saveTimer = null;
    this._bound = false;
    this._editing = new Set();
    this._hasRendered = false;
  }

  setConfig(config) {
    if (!config || !Array.isArray(config.symbols) || config.symbols.length === 0) {
      throw new Error("symbols must be a non-empty array");
    }

    this._config = {
      title: config.title ?? "Price levels",
      show_price: config.show_price ?? true,
      symbols: config.symbols.map((s) => String(s).toUpperCase()),
    };

    for (const symbol of this._config.symbols) {
      if (!this._levels[symbol]) {
        this._levels[symbol] = {
          upper_1: "",
          upper_2: "",
          lower_1: "",
          lower_2: "",
        };
      }
    }

    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._syncFromHass();
    if (!this._hasRendered) {
      this._render();
      this._hasRendered = true;
    } else {
      this._refreshFromHass();
    }
  }

  getCardSize() {
    return Math.max(4, this._config.symbols.length + 2);
  }

  _levelMeta() {
    return {
      lower_2: { label: "Lower (Far)", hint: "Extended support", cls: "lower2" },
      lower_1: { label: "Lower (Near)", hint: "Support / put target", cls: "lower1" },
      upper_1: { label: "Upper (Near)", hint: "Resistance / call target", cls: "upper1" },
      upper_2: { label: "Upper (Far)", hint: "Extended resistance", cls: "upper2" },
    };
  }

  _priceEntityId(symbol) {
    return `sensor.market_${symbol.toLowerCase()}`;
  }

  _levelEntityId(symbol, levelKey) {
    return `number.market_${symbol.toLowerCase()}_${levelKey}`;
  }

  _switchEntityId(symbol) {
    return `switch.market_${symbol.toLowerCase()}_alerts`;
  }

  _getState(entityId) {
    return this._hass?.states?.[entityId] ?? null;
  }

  _parseNumber(stateObj) {
    if (!stateObj) return null;
    const value = Number(stateObj.state);
    return Number.isFinite(value) ? value : null;
  }

  _normalizeDraftNumber(rawValue) {
    if (rawValue === "" || rawValue === null || rawValue === undefined) {
      return 0;
    }
    const value = Number(rawValue);
    return Number.isFinite(value) ? value : 0;
  }

  _isFieldDirty(symbol, levelKey) {
    const draft = this._normalizeDraftNumber(this._levels[symbol]?.[levelKey] ?? "");
    const stateObj = this._getState(this._levelEntityId(symbol, levelKey));
    const current = this._parseNumber(stateObj) ?? 0;
    return draft !== current;
  }

  _recomputeDirty() {
    this._dirty = false;

    for (const symbol of this._config.symbols ?? []) {
      for (const levelKey of Object.keys(this._levelMeta())) {
        if (this._isFieldDirty(symbol, levelKey)) {
          this._dirty = true;
          return;
        }
      }
    }
  }

  _formatPrice(value) {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      return "—";
    }
    return `$${value.toFixed(2)}`;
  }

  _distanceBadge(price, level) {
    if (!Number.isFinite(price) || !Number.isFinite(level) || level === 0) {
      return "";
    }

    const diff = price - level;
    const pct = (diff / level) * 100;
    const above = diff >= 0;

    return `
<span class="badge ${above ? " above" : "below"}">
  ${above ? "+" : ""}${diff.toFixed(2)} (${above ? "+" : ""}${pct.toFixed(1)}%)
</span>
`;
  }


  _validateLevels() {
    for (const symbol of this._config.symbols ?? []) {
      const u1 = this._normalizeDraftNumber(this._levels[symbol]?.upper_1);
      const u2 = this._normalizeDraftNumber(this._levels[symbol]?.upper_2);
      const l1 = this._normalizeDraftNumber(this._levels[symbol]?.lower_1);
      const l2 = this._normalizeDraftNumber(this._levels[symbol]?.lower_2);

      // Ignore disabled levels (0)
      if (u1 !== 0 && u2 !== 0 && u2 <= u1) {
        return {
          ok: false,
          message: `${symbol}: Upper (Far) must be greater than Upper (Near)`,
          fields: [`${symbol}:upper_1`, `${symbol}:upper_2`],
        };
      }

      if (l1 !== 0 && l2 !== 0 && l2 >= l1) {
        return {
          ok: false,
          message: `${symbol}: Lower (Far) must be less than Lower (Near)`,
          fields: [`${symbol}:lower_1`, `${symbol}:lower_2`],
        };
      }
    }

    return { ok: true };
  }

  _syncFromHass() {
    if (!this._hass) return;

    for (const symbol of this._config.symbols) {
      if (!this._levels[symbol]) {
        this._levels[symbol] = {
          upper_1: "",
          upper_2: "",
          lower_1: "",
          lower_2: "",
        };
      }

      const switchObj = this._getState(this._switchEntityId(symbol));
      this._alertsEnabled[symbol] = switchObj ? switchObj.state === "on" : true;

      for (const levelKey of Object.keys(this._levelMeta())) {
        const editKey = `${symbol}:${levelKey}`;
        if (this._editing.has(editKey)) {
          continue;
        }

        const stateObj = this._getState(this._levelEntityId(symbol, levelKey));
        if (!stateObj) continue;

        const val = this._parseNumber(stateObj);
        this._levels[symbol][levelKey] = val === null ? "" : String(val);
      }
    }

    this._recomputeDirty();
  }

  _onInput(symbol, levelKey, value) {
    this._levels[symbol][levelKey] = value;
    this._error = null;
    this._saved = false;

    this.shadowRoot
      ?.querySelectorAll(".level-invalid")
      .forEach((el) => el.classList.remove("level-invalid"));

    this._recomputeDirty();
    this._refreshStatusOnly();
  }


  _refreshStatusOnly() {
    if (!this.shadowRoot) return;

    const button = this.shadowRoot.getElementById("save-btn");
    if (button) {
      button.textContent = this._saving
        ? "Saving..."
        : this._saved
          ? "Saved"
          : this._dirty
            ? "Save levels"
            : "No changes";
      button.disabled = this._saving || !this._dirty;
      button.style.opacity = this._saving ? "0.7" : "1";
      button.style.background = this._saved
        ? "#16a34a"
        : this._dirty
          ? "var(--primary-color)"
          : "var(--disabled-color)";
    }

    const status = this.shadowRoot.getElementById("status-msg");
    if (status) {
      if (this._error) {
        status.className = "status error";
        status.textContent = this._error;
      } else if (this._saved) {
        status.className = "status ok";
        status.textContent = "Levels saved";
      } else if (this._dirty) {
        status.className = "status hint";
        status.textContent = "Unsaved changes";
      } else {
        status.className = "status hint";
        status.textContent = "Set 0 to disable a level.";
      }
    }
  }

  _refreshFromHass() {
    if (!this.shadowRoot) return;

    for (const symbol of this._config.symbols ?? []) {

      // --- update row enabled/disabled visual state ---
      const row = this.shadowRoot.querySelector(
        `tr[data-symbol-row="${symbol}"]`
      );

      if (row) {
        const enabled = Boolean(this._alertsEnabled[symbol]);
        row.classList.toggle("row-disabled", !enabled);
      }

      const priceEl = this.shadowRoot.querySelector(`[data-price-symbol="${symbol}"]`);
      if (priceEl) {
        const price = this._parseNumber(this._getState(this._priceEntityId(symbol)));
        priceEl.textContent = this._config.show_price ? this._formatPrice(price) : "";
      }

      const switchInput = this.shadowRoot.querySelector(
        `input[data-symbol="${symbol}"][data-role="alerts-switch"]`
      );
      if (switchInput instanceof HTMLInputElement) {
        const enabled = Boolean(this._alertsEnabled[symbol]);
        switchInput.checked = enabled;
      }

      const switchLabel = this.shadowRoot.querySelector(
        `[data-alerts-label="${symbol}"]`
      );
      if (switchLabel) {
        switchLabel.textContent = this._alertsEnabled[symbol] ? "On" : "Off";
      }

      for (const levelKey of Object.keys(this._levelMeta())) {
        const editKey = `${symbol}:${levelKey}`;
        const input = this.shadowRoot.querySelector(
          `input[data-symbol="${symbol}"][data-level="${levelKey}"]`
        );

        if (!(input instanceof HTMLInputElement)) continue;

        if (input.dataset.role === "alerts-switch") {
          const enabled = Boolean(this._alertsEnabled[symbol]);
          input.checked = enabled;

          const label = this.shadowRoot.querySelector(
            `[data-alerts-label="${symbol}"]`
          );
          if (label) {
            label.textContent = enabled ? "On" : "Off";
          }
        }

        if (!this._editing.has(editKey)) {
          const raw = this._levels[symbol]?.[levelKey] ?? "";
          input.value = raw;
        }
      }
    }

    this._refreshStatusOnly();
  }

  async _toggleAlerts(symbol, enabled) {
    if (!this._hass) return;

    const row = this.shadowRoot.querySelector(
      `tr[data-symbol-row="${symbol}"]`
    );

    row?.classList.add("toggle-saving");

    this._error = null;
    this._alertsEnabled[symbol] = enabled;
    this._refreshFromHass();

    try {
      await this._hass.callService(
        "switch",
        enabled ? "turn_on" : "turn_off",
        {
          entity_id: this._switchEntityId(symbol),
        }
      );
    } catch (err) {
      this._alertsEnabled[symbol] = !enabled;
      this._error = err?.message || String(err);
      this._refreshFromHass();
    } finally {
      row?.classList.remove("toggle-saving");
    }

  }

  _highlightInvalidFields(fields) {
    if (!this.shadowRoot) return;

    // Clear previous highlights
    this.shadowRoot
      .querySelectorAll(".level-invalid")
      .forEach((el) => el.classList.remove("level-invalid"));

    for (const key of fields) {
      const [symbol, level] = key.split(":");

      const input = this.shadowRoot.querySelector(
        `input[data-symbol="${symbol}"][data-level="${level}"]`
      );

      if (input) {
        input.classList.add("level-invalid");
      }
    }
  }

  async _saveAll() {
    if (!this._hass || this._saving) return;

    const validation = this._validateLevels();
    if (!validation.ok) {
      this._error = validation.message;
      this._highlightInvalidFields(validation.fields);
      this._refreshStatusOnly();
      return;
    }

    this._saving = true;
    this._saved = false;
    this._dirty = false;
    this._error = null;
    this._refreshStatusOnly();

    try {
      for (const symbol of this._config.symbols) {
        for (const levelKey of Object.keys(this._levelMeta())) {
          const rawValue = this._levels[symbol]?.[levelKey] ?? "";
          const value = rawValue === "" ? 0 : Number(rawValue);

          await this._hass.callService("number", "set_value", {
            entity_id: this._levelEntityId(symbol, levelKey),
            value: Number.isFinite(value) ? value : 0,
          });
        }
      }

      this._saving = false;
      this._saved = true;
      this._error = null;

      clearTimeout(this._saveTimer);
      this._saveTimer = setTimeout(() => {
        this._saved = false;
        this._refreshStatusOnly();
      }, 2500);

      this._refreshStatusOnly();
    } catch (err) {
      this._saving = false;
      this._saved = false;
      this._error = err?.message || String(err);
      this._refreshStatusOnly();
    }
  }

  _bindEvents() {
    if (this._bound) return;

    this.shadowRoot.addEventListener("focusin", (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (!target.dataset.symbol || !target.dataset.level) return;

      this._editing.add(`${target.dataset.symbol}:${target.dataset.level}`);
    });

    this.shadowRoot.addEventListener("focusout", (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (!target.dataset.symbol || !target.dataset.level) return;

      this._editing.delete(`${target.dataset.symbol}:${target.dataset.level}`);
    });

    this.shadowRoot.addEventListener("input", (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (!target.dataset.symbol || !target.dataset.level) return;

      this._onInput(target.dataset.symbol, target.dataset.level, target.value);
    });

    this.shadowRoot.addEventListener("click", (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLElement)) return;

      if (target.id === "save-btn") {
        this._saveAll();
      }
      if (target.dataset.role === "alerts-switch") {
        const symbol = target.dataset.symbol;
        if (!symbol) return;

        this._toggleAlerts(symbol, target.checked);
      }
    });

    this.shadowRoot.addEventListener("change", (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLInputElement)) return;

      if (target.dataset.role === "alerts-switch") {
        ev.stopPropagation();
      }
    });

    // Press Enter inside any level field to save
    this.shadowRoot.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;

      const target = ev.target;

      if (!(target instanceof HTMLInputElement)) return;

      // Only trigger if something actually changed
      if (!this._dirty) return;

      ev.preventDefault();

      this._saveAll();
    });

    this._bound = true;
  }

  _render() {
    if (!this.shadowRoot) return;

    const meta = this._levelMeta();
    const symbols = this._config.symbols ?? [];

    const rows = symbols
      .map((symbol) => {
        const alertsEnabled = this._alertsEnabled[symbol] ?? true;
        const price = this._parseNumber(this._getState(this._priceEntityId(symbol)));
        const priceDisplay = this._config.show_price ? this._formatPrice(price) : "";

        const cells = Object.entries(meta)
          .map(([levelKey, levelMeta]) => {
            const raw = this._levels[symbol]?.[levelKey] ?? "";
            const numericValue = raw === "" ? null : Number(raw);
            const badge =
              Number.isFinite(price) && Number.isFinite(numericValue)
                ? this._distanceBadge(price, numericValue)
                : "";

            return `
<td class="cell">
  <div class="input-wrap">
    <input type="number" step="0.5" inputmode="decimal" placeholder="0" value="${raw}" data-symbol="${symbol}"
      data-level="${levelKey}" />
    ${badge}
  </div>
</td>
`;
          })
          .join("");

        return `
<tr
  data-symbol-row="${symbol}"
  class="${alertsEnabled ? "" : "row-disabled"}">
  <td class="symbol-col">
    <div class="symbol">${symbol}</div>
    ${this._config.show_price ? `<div class="price" data-price-symbol="${symbol}">${priceDisplay}</div>` : ""}
  </td>
  <td class="alerts-col">
    <label class="toggle-wrap">
      <input
        class="toggle-native"
        type="checkbox"
        data-symbol="${symbol}"
        data-role="alerts-switch"
        title="Enable or disable all alerts for this symbol"
        ${alertsEnabled ? "checked" : ""}
      />
      <span class="toggle-box" aria-hidden="true"></span>
      <span class="toggle-label" data-alerts-label="${symbol}">
        ${alertsEnabled ? "On" : "Off"}
      </span>
    </label>
  </td>
  ${cells}
</tr>
`;
      })
      .join("");

    const headers = Object.values(meta)
      .map(
        (m) => `
          <th>
            <div class="head-label">${m.label}</div>
            <div class="head-hint">${m.hint}</div>
          </th>
        `).join("");

    const alertsHeader = `
       <th class="alerts-head">
         <div class="head-label">Alerts</div>
         <div class="head-hint">Symbol on/off</div>
       </th>
     `;
    const saveLabel = this._saving ? "Saving..." : this._saved ? "Saved" : "Save levels";
    const statusHtml = this._error
      ? `<div id="status-msg" class="status error">${this._error}</div>`
      : this._saved
        ? `<div id="status-msg" class="status ok">Levels saved</div>`
        : `<div id="status-msg" class="status hint">Set 0 to disable a level.</div>`;

    this.shadowRoot.innerHTML = `
<style>
  :host {
    display: block;
  }

  ha-card {
    padding: 16px;
  }

  .header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 14px;
  }

  .row-disabled {
    opacity: 0.6;
    transition: opacity 0.15s ease;
  }

  .row-disabled input[type="number"] {
    background: var(--disabled-color);
    color: var(--secondary-text-color);
    border-color: var(--divider-color);
  }

  .alerts-col,
  .alerts-head {
    text-align: center;
    vertical-align: middle;
    white-space: nowrap;
    width: 1%;
    padding: 8px 6px;
  }

  .toggle-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    width: 72px;
    margin: 0 auto;
    position: relative;
    cursor: pointer;
  }

  .toggle-native {
    position: absolute;
    opacity: 0;
    width: 16px;
    height: 16px;
    margin: 0;
    inset: 0 auto auto 50%;
    transform: translateX(-50%);
    pointer-events: auto;
  }
  .toggle-box {
    display: block;
    width: 16px;
    height: 16px;
    border: 2px solid var(--secondary-text-color);
    border-radius: 4px;
    box-sizing: border-box;
    position: relative;
    flex: 0 0 auto;
  }

  .toggle-native:checked + .toggle-box::after {
    content: "";
    position: absolute;
    left: 4px;
    top: 0px;
    width: 4px;
    height: 8px;
    border: solid var(--primary-color);
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }

  .toggle-saving {
    opacity: 0.6;
    pointer-events: none;
  }

  .toggle-native:focus-visible + .toggle-box {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
    }

  .toggle-label {
    font-size: 11px;
    font-weight: 600;
    color: var(--secondary-text-color);
    text-align: center;
    line-height: 1;
    display: block;
  }

  .title {
    font-size: 16px;
    font-weight: 600;
    line-height: 1.2;
  }

  .sub {
    margin-top: 4px;
    color: var(--secondary-text-color);
    font-size: 12px;
  }

  .level-invalid {
    border-color: var(--error-color);
    background: rgba(255, 0, 0, 0.06);
  }

  button {
    border: none;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    color: white;

    background: $ {
      this._saved ? "#16a34a": "var(--primary-color)"
    }

    ;

    opacity: $ {
      this._saving ? "0.7": "1"
    }

    ;
  }

  button:disabled {
    cursor: default;
  }

  .table-wrap {
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
  }

  th,
  td {
    border-bottom: 1px solid var(--divider-color);
  }

  th {
    padding: 8px 6px 10px;
    text-align: center;
    width: 1%;
    vertical-align: bottom;
  }

  .head-label {
    font-size: 12px;
    font-weight: 600;
  }

  .head-hint {
    margin-top: 2px;
    color: var(--secondary-text-color);
    font-size: 10px;
    font-weight: 400;
  }

  .symbol-col {
    padding: 10px 8px;
    min-width: 92px;
    white-space: nowrap;
    vertical-align: top;
  }

  .symbol {
    font-size: 14px;
    font-weight: 700;
  }

  .price {
    margin-top: 2px;
    font-size: 12px;
    color: var(--secondary-text-color);
  }

  .cell {
    padding: 8px 6px;
    vertical-align: top;
    text-align: center;
  }

  .input-wrap {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: center;
  }

  input {
    width: 72px;
    min-width: 72px;
    padding: 6px 8px;
    border: 1px solid var(--divider-color);
    border-radius: 8px;
    background: var(--card-background-color);
    color: var(--primary-text-color);
    font-size: 13px;
    text-align: right;
    outline: none;
  }

  input:focus {
    border-color: var(--primary-color);
  }

  .badge {
    display: inline-block;
    align-self: center;
    text-align: center;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 6px;
    border-radius: 999px;
    white-space: nowrap;
  }

  .badge.above {
    color: #166534;
    background: #dcfce7;
  }

  .badge.below {
    color: #991b1b;
    background: #fee2e2;
  }

  .status {
    margin-top: 12px;
    font-size: 12px;
  }

  .status.hint {
    color: var(--secondary-text-color);
  }

  .status.ok {
    color: #15803d;
    font-weight: 600;
  }

  .status.error {
    color: var(--error-color);
    font-weight: 600;
  }
</style>

<ha-card>
  <div class="header">
    <div>
      <div class="title">${this._config.title}</div>
      <div class="sub">Edit Finnhub trigger levels by symbol.</div>
    </div>
    <button id="save-btn" ${this._saving ? "disabled" : ""}>${saveLabel}</button>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th></th>
          ${alertsHeader}
          ${headers}
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  </div>

  ${statusHtml}
</ha-card>
`;

    this._bindEvents();
  }
}

customElements.define("finnhub-levels-card", FinnhubLevelsCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "finnhub-levels-card",
  name: "Finnhub Levels Card",
  description: "Edit number.market_<symbol>_<level> entities for Finnhub price levels.",
});
console.info("finnhub-levels-card build 2026-03-27-checkbox-center-3");