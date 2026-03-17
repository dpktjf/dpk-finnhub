"""Constants for the Finnhub integration."""

DOMAIN = "finnhub"

CONF_SYMBOLS = "symbols"

# FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
FINNHUB_QUOTE_URL = "http://127.0.0.1:5000/api/v1/quote"


# Rate limiter: stay under 60/min with a safety buffer
RATE_LIMIT_CALLS = 55
RATE_LIMIT_PERIOD = 60.0
RATE_LIMIT_BURST = 28
RATE_LIMIT_BURST_PERIOD = 1.0

# Default polling interval in seconds (recalculated dynamically per symbol count)
DEFAULT_SCAN_INTERVAL_SECONDS = 60

ATTR_OPEN = "open"
ATTR_HIGH = "high"
ATTR_LOW = "low"
ATTR_PREVIOUS_CLOSE = "previous_close"
ATTR_CHANGE = "change"
ATTR_CHANGE_PERCENT = "change_percent"
ATTR_SYMBOL = "symbol"
