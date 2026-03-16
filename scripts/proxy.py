import random
import time
from flask import Flask, jsonify, request

app = Flask(__name__)


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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
