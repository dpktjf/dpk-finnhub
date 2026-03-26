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
    this._saving = false;
    this._saved = false;
    this._error = null;
    this._saveTimer = null;
    this._bound = false;
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
    this._render();
  }

  getCardSize() {
    return Math.max(4, this._config.symbols.length + 2);
  }

  _levelMeta() {
    return {
      upper_1: { label: "Upper 1", hint: "Resistance / call target", cls: "upper1" },
      upper_2: { label: "Upper 2", hint: "Extended resistance", cls: "upper2" },
      lower_1: { label: "Lower 1", hint: "Support / put target", cls: "lower1" },
      lower_2: { label: "Lower 2", hint: "Extended support", cls: "lower2" },
    };
  }

  _priceEntityId(symbol) {
    return `sensor.market_${symbol.toLowerCase()}`;
  }

  _levelEntityId(symbol, levelKey) {
    return `number.market_${symbol.toLowerCase()}_${levelKey}`;
  }

  _getState(entityId) {
    return this._hass?.states?.[entityId] ?? null;
  }

  _parseNumber(stateObj) {
    if (!stateObj) return null;
    const value = Number(stateObj.state);
    return Number.isFinite(value) ? value : null;
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

      for (const levelKey of Object.keys(this._levelMeta())) {
        const stateObj = this._getState(this._levelEntityId(symbol, levelKey));
        if (!stateObj) continue;

        const val = this._parseNumber(stateObj);
        this._levels[symbol][levelKey] = val === null ? "" : String(val);
      }
    }
  }

  _onInput(symbol, levelKey, value) {
    this._levels[symbol][levelKey] = value;
    this._saved = false;
    this._error = null;
    this._refreshStatusOnly();
  }


  _refreshStatusOnly() {
    if (!this.shadowRoot) return;

    const button = this.shadowRoot.getElementById("save-btn");
    if (button) {
      button.textContent = this._saving ? "Saving..." : this._saved ? "Saved" : "Save levels";
      button.disabled = this._saving;
      button.style.opacity = this._saving ? "0.7" : "1";
      button.style.background = this._saved ? "#16a34a" : "var(--primary-color)";
    }

    const status = this.shadowRoot.getElementById("status-msg");
    if (status) {
      if (this._error) {
        status.className = "status error";
        status.textContent = this._error;
      } else if (this._saved) {
        status.className = "status ok";
        status.textContent = "Levels saved";
      } else {
        status.className = "status hint";
        status.textContent = "Set 0 to disable a level.";
      }
    }
  }

  async _saveAll() {
    if (!this._hass || this._saving) return;

    this._saving = true;
    this._saved = false;
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
    });

    this._bound = true;
  }

  _render() {
    if (!this.shadowRoot) return;

    const meta = this._levelMeta();
    const symbols = this._config.symbols ?? [];

    const rows = symbols
      .map((symbol) => {
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
<tr>
  <td class="symbol-col">
    <div class="symbol">${symbol}</div>
    ${this._config.show_price ? `<div class="price">${priceDisplay}</div>` : ""}
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
`
      )
      .join("");

    const saveLabel = this._saving ? "Saving..." : this._saved ? "Saved" : "Save levels";
    const statusHtml = this._error
      ? `<div class="status error">${this._error}</div>`
      : this._saved
        ? `<div class="status ok">Levels saved</div>`
        : `<div class="status hint">Set 0 to disable a level.</div>`;

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
  }

  th,
  td {
    border-bottom: 1px solid var(--divider-color);
  }

  th {
    padding: 8px 6px 10px;
    text-align: center;
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
  }

  .input-wrap {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: stretch;
  }

  input {
    width: 88px;
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
    align-self: flex-end;
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