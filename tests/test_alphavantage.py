"""Tests for the Alpha-Vantage HTTP fetcher (MockTransport-driven, offline)."""

from datetime import date

import httpx
import pytest

from price_space_llm.ingestion.alphavantage import (
    AlphaVantageError,
    AlphaVantageRateLimitError,
    AlphaVantageResponseError,
    make_alphavantage_fetcher,
)


def _canned_intraday(n_bars: int = 500) -> dict:
    """Build an Alpha-Vantage-shaped response with `n_bars` bars for 2015-06."""
    series = {}
    for i in range(n_bars):
        # Fake but monotonic timestamps within 2015-06.
        day = 1 + (i // 26)
        bar_of_day = i % 26
        hh = 9 + (bar_of_day // 4)
        mm = 30 + 15 * (bar_of_day % 4)
        if mm >= 60:
            hh += mm // 60
            mm = mm % 60
        ts = f"2015-06-{day:02d} {hh:02d}:{mm:02d}:00"
        series[ts] = {
            "1. open": "200.0000",
            "2. high": "201.0000",
            "3. low": "199.5000",
            "4. close": "200.5000",
            "5. volume": "1000000",
        }
    return {
        "Meta Data": {
            "1. Information": "Intraday (15min) open, high, low, close prices and volume",
            "2. Symbol": "SPY",
            "3. Last Refreshed": f"2015-06-{1 + (n_bars - 1) // 26:02d} 20:00:00",
            "4. Interval": "15min",
            "5. Output Size": "Full",
            "6. Time Zone": "US/Eastern",
        },
        "Time Series (15min)": series,
    }


def _client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x")


def test_fetcher_returns_fetch_result_on_clean_response():
    def handler(request):
        return httpx.Response(200, json=_canned_intraday(n_bars=546))

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    result = fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))
    assert result["actual_frequency"] == "15min"
    assert result["timezone"] == "UTC"
    assert result["timestamp_semantics"] == "bar_close"
    assert result["missing_fraction"] == pytest.approx(0.0)
    assert result["earliest_timestamp"].startswith("2015-06-01")
    assert result["earliest_timestamp"].endswith("+00:00")


def test_fetcher_missing_fraction_scales_with_bar_count():
    def handler(request):
        # 273 bars = half of 546-bar expectation for a full month.
        return httpx.Response(200, json=_canned_intraday(n_bars=273))

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    result = fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))
    assert result["missing_fraction"] == pytest.approx(0.5, abs=0.01)


def test_fetcher_normalises_us_eastern_to_utc():
    """A 09:30 US-Eastern bar becomes 14:30 UTC under the EST -5 fixed offset."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "Meta Data": {"4. Interval": "15min"},
                "Time Series (15min)": {
                    "2015-06-15 09:30:00": {
                        "1. open": "200",
                        "2. high": "201",
                        "3. low": "199",
                        "4. close": "200.5",
                        "5. volume": "1000",
                    },
                },
            },
        )

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    result = fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))
    assert result["earliest_timestamp"] == "2015-06-15T14:30:00+00:00"


def test_fetcher_raises_on_error_message_payload():
    def handler(request):
        return httpx.Response(200, json={"Error Message": "Invalid API call"})

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    with pytest.raises(AlphaVantageResponseError, match="Invalid API call"):
        fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))


def test_fetcher_raises_rate_limit_on_note_payload():
    def handler(request):
        return httpx.Response(200, json={"Note": "Thank you for using Alpha Vantage!..."})

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    with pytest.raises(AlphaVantageRateLimitError):
        fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))


def test_fetcher_raises_rate_limit_on_information_payload():
    def handler(request):
        return httpx.Response(200, json={"Information": "detected free-tier daily cap"})

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    with pytest.raises(AlphaVantageRateLimitError):
        fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))


def test_fetcher_raises_on_non_200():
    def handler(request):
        return httpx.Response(500, text="internal server error")

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    with pytest.raises(httpx.HTTPStatusError):
        fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))


def test_fetcher_raises_not_implemented_on_unsupported_channel():
    def handler(request):
        return httpx.Response(200, json={})

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    with pytest.raises(NotImplementedError, match="Sprint 019 fetcher supports"):
        fetcher("macro", "CPI", "mcp_av", date(2015, 6, 15))


def test_fetcher_sends_expected_query_params():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_canned_intraday(n_bars=546))

    fetcher = make_alphavantage_fetcher("test-key-abc", client=_client_with(handler))
    fetcher("market_context", "VIX", "mcp_av", date(2018, 3, 15))
    url = captured["url"]
    assert "function=TIME_SERIES_INTRADAY" in url
    assert "symbol=VIX" in url
    assert "interval=15min" in url
    assert "outputsize=full" in url
    assert "month=2018-03" in url
    assert "apikey=test-key-abc" in url


def test_fetcher_marks_empty_series_as_fully_missing():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "Meta Data": {"4. Interval": "15min"},
                "Time Series (15min)": {},
            },
        )

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    result = fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))
    assert result["missing_fraction"] == 1.0
    # Vocabulary requires ISO-8601 datetime_utc; epoch-zero marks "no data".
    assert result["earliest_timestamp"] == "1970-01-01T00:00:00+00:00"
    assert result["revision_behavior"] == "empty_series"


def test_alphavantage_error_hierarchy():
    """Both concrete errors are AlphaVantageError subclasses (for one-catch handling)."""
    assert issubclass(AlphaVantageResponseError, AlphaVantageError)
    assert issubclass(AlphaVantageRateLimitError, AlphaVantageError)
