# ruff: noqa no lint...

import random
import stat
import time
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# --- Market status state: "open" | "closed" | "holiday" ---
market_state = "open"
state = {"market": "open", "auth_error": False}
MARKET_RESPONSES = {
    "open": {
        "exchange": "US",
        "holiday": None,
        "isOpen": True,
        "session": "regular",
        "timezone": "America/New_York",
    },
    "closed": {
        "exchange": "US",
        "holiday": None,
        "isOpen": False,
        "session": "pre-market",
        "timezone": "America/New_York",
    },
    "holiday": {
        "exchange": "US",
        "holiday": "Thanksgiving Day",
        "isOpen": False,
        "session": "holiday",
        "timezone": "America/New_York",
    },
}


@app.route("/api/v1/quote")
def quote():
    if state["auth_error"]:
        return jsonify({"error": "Invalid API key."}), 401
    symbol = request.args.get("symbol", "SPY")

    # Base data — randomise the current price (c) around a realistic range
    base_price = 662.29
    c = round(random.uniform(base_price * 0.97, base_price * 1.03), 2)
    pc = 666.06
    d = round(c - pc, 2)
    dp = round((d / pc) * 100, 3)

    data = {
        "c": c,
        "d": d,
        "dp": dp,
        "h": 672.335,
        "l": 661.36,
        "o": 669.27,
        "pc": pc,
        "t": int(time.time()),
    }

    return jsonify(data)


@app.route("/api/v1/status/open", methods=["GET", "POST"])
def status_open() -> Response:
    state["market"] = "open"
    return jsonify({"state": state["market"], "message": "Market set to OPEN"})


@app.route("/api/v1/status/close", methods=["GET", "POST"])
def status_close() -> Response:
    state["market"] = "closed"
    return jsonify({"state": state["market"], "message": "Market set to CLOSED"})


@app.route("/api/v1/status/holiday", methods=["GET", "POST"])
def status_holiday() -> Response:
    state["market"] = "holiday"
    return jsonify({"state": state["market"], "message": "Market set to HOLIDAY"})


@app.route("/api/v1/status/auth", methods=["GET", "POST"])
def status_auth() -> Response:
    state["auth_error"] = not state["auth_error"]
    flag = state["auth_error"]
    return jsonify(
        {
            "auth_error": flag,
            "message": f"Auth error {'ENABLED' if flag else 'DISABLED'}",
        }
    )


@app.route("/api/v1/stock/market-status")
def status():
    if state["auth_error"]:
        return jsonify({"error": "Invalid API key."}), 401
    response = MARKET_RESPONSES.get(state["market"], MARKET_RESPONSES["open"])
    return jsonify({**response, "t": int(time.time())})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
