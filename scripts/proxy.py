import random
import stat
import time
from flask import Flask, jsonify, request

app = Flask(__name__)

# --- Market status state: "open" | "closed" | "holiday" ---
market_state = "open"

stat_open = {
    "exchange": "US",
    "holiday": "",
    "isOpen": True,
    "session": "regular",
    "t": int(time.time()),
    "timezone": "America/New_York",
}
stat_closed = {
    "exchange": "US",
    "holiday": "",
    "isOpen": False,
    "session": "pre-market",
    "t": int(time.time()),
    "timezone": "America/New_York",
}
stat_holiday = {
    "exchange": "US",
    "holiday": "Christmas",
    "isOpen": False,
    "session": "",
    "t": int(time.time()),
    "timezone": "America/New_York",
}


@app.route("/api/v1/quote")
def quote():
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
def status_open():
    global market_state, stat_open
    market_state = "open"
    return jsonify(stat_open)


@app.route("/api/v1/status/close", methods=["GET", "POST"])
def status_close():
    global market_state, stat_closed
    market_state = "closed"
    return jsonify(stat_closed)


@app.route("/api/v1/status/holiday", methods=["GET", "POST"])
def status_holiday():
    global market_state, stat_holiday
    market_state = "holiday"
    return jsonify(stat_holiday)


@app.route("/api/v1/stock/market-status")
def status():
    market = request.args.get("market", "US")
    global market_state, stat_holiday, stat_closed, stat_open
    if market_state == "open":
        return jsonify(stat_open)
    elif market_state == "closed":
        return jsonify(stat_closed)
    elif market_state == "holiday":
        return jsonify(stat_holiday)
    else:
        return jsonify(stat_open)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
