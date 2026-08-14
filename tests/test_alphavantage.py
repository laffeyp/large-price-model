"""Tests for the Alpha-Vantage HTTP fetcher (MockTransport-driven, offline)."""

from datetime import date

import httpx
import pytest

from price_space_llm.ingestion.alphavantage import (
    AlphaVantageError,
    AlphaVantageRateLimitError,
    AlphaVantageResponseError,
    alphavantage_extract_metadata,
    alphavantage_index_extract_metadata,
    alphavantage_macro_extract_metadata,
    alphavantage_put_call_ratio_extract_metadata,
    make_alphavantage_fetcher,
    make_alphavantage_raw_fetcher,
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
    assert result.actual_frequency == "15min"
    assert result.timezone == "UTC"
    assert result.timestamp_semantics == "bar_close"
    assert result.missing_fraction == pytest.approx(0.0)
    assert result.earliest_timestamp.startswith("2015-06-01")
    assert result.earliest_timestamp.endswith("+00:00")


def test_fetcher_missing_fraction_scales_with_bar_count():
    def handler(request):
        # 273 bars = half of 546-bar expectation for a full month.
        return httpx.Response(200, json=_canned_intraday(n_bars=273))

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    result = fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))
    assert result.missing_fraction == pytest.approx(0.5, abs=0.01)


def test_fetcher_normalises_us_eastern_to_utc():
    """A 09:30 US-Eastern bar in June (EDT, UTC-4) becomes 13:30 UTC. Sprint 043."""

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
    assert result.earliest_timestamp == "2015-06-15T13:30:00+00:00"


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


def test_fetcher_raises_on_empty_series():
    """Empty Time Series means no observations; the fetcher raises rather than fabricate.

    Sprint 023 correction: the earlier fill-value path (epoch-zero timestamps +
    `revision_behavior="empty_series"`) shipped a lie in the trace. The caller
    (probe) now catches the raise and emits `CHANNEL_FETCH_FAILED` — an
    incident tag whose payload is honest about the failure.
    """

    def handler(request):
        return httpx.Response(
            200,
            json={
                "Meta Data": {"4. Interval": "15min"},
                "Time Series (15min)": {},
            },
        )

    fetcher = make_alphavantage_fetcher("k", client=_client_with(handler))
    with pytest.raises(AlphaVantageResponseError, match="empty Time Series"):
        fetcher("target", "SPY", "mcp_av", date(2015, 6, 15))


def test_alphavantage_error_hierarchy():
    """Both concrete errors are AlphaVantageError subclasses (for one-catch handling)."""
    assert issubclass(AlphaVantageResponseError, AlphaVantageError)
    assert issubclass(AlphaVantageRateLimitError, AlphaVantageError)


# make_alphavantage_raw_fetcher --------------------------------------------


def test_raw_fetcher_returns_dict_verbatim():
    payload = _canned_intraday(n_bars=10)

    def handler(request):
        return httpx.Response(200, json=payload)

    fetcher = make_alphavantage_raw_fetcher("k", client=_client_with(handler))
    out = fetcher("TIME_SERIES_INTRADAY", {"symbol": "SPY", "interval": "15min"})
    assert out == payload


def test_raw_fetcher_passes_params_and_apikey():
    captured: dict = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_canned_intraday(n_bars=5))

    fetcher = make_alphavantage_raw_fetcher("test-key-abc", client=_client_with(handler))
    fetcher("TIME_SERIES_INTRADAY", {"symbol": "SPY", "month": "2024-06"})
    assert "function=TIME_SERIES_INTRADAY" in captured["url"]
    assert "symbol=SPY" in captured["url"]
    assert "month=2024-06" in captured["url"]
    assert "apikey=test-key-abc" in captured["url"]


def test_raw_fetcher_raises_on_error_message():
    def handler(request):
        return httpx.Response(200, json={"Error Message": "boom"})

    fetcher = make_alphavantage_raw_fetcher("k", client=_client_with(handler))
    with pytest.raises(AlphaVantageResponseError, match="boom"):
        fetcher("TIME_SERIES_INTRADAY", {"symbol": "SPY"})


def test_raw_fetcher_raises_on_note_rate_limit():
    def handler(request):
        return httpx.Response(200, json={"Note": "throttled"})

    fetcher = make_alphavantage_raw_fetcher("k", client=_client_with(handler))
    with pytest.raises(AlphaVantageRateLimitError, match="throttled"):
        fetcher("TIME_SERIES_INTRADAY", {"symbol": "SPY"})


# alphavantage_extract_metadata --------------------------------------------


def test_extract_metadata_finds_batch_high_watermark():
    payload = _canned_intraday(n_bars=100)
    meta = alphavantage_extract_metadata(payload)
    assert meta.rows_written == 100
    # value_time is the newest bar in UTC (US/Eastern -5 fixed → UTC +5 shift)
    assert meta.value_time.year == 2015
    assert meta.value_time.month == 6
    # known_at is value_time + 1 minute
    assert (meta.known_at - meta.value_time).total_seconds() == 60.0


def test_extract_metadata_raises_on_missing_time_series_key():
    with pytest.raises(AlphaVantageResponseError, match="no 'Time Series"):
        alphavantage_extract_metadata({"Meta Data": {}})


def test_extract_metadata_raises_on_empty_series():
    with pytest.raises(AlphaVantageResponseError, match="empty Time Series"):
        alphavantage_extract_metadata({"Time Series (15min)": {}})


# INDEX_DATA extractor (Sprint 038) ----------------------------------------


def _canned_index_daily(n_rows: int = 3) -> dict:
    """Build an Alpha-Vantage INDEX_DATA-shaped VIX daily response."""
    return {
        "symbol": "VIX",
        "name": "Cboe Volatility Index",
        "interval": "daily",
        "data": [
            {
                "date": f"2024-06-{28 - i:02d}",
                "open": "12.5",
                "high": "13.0",
                "low": "12.4",
                "close": f"12.{50 + i}",
            }
            for i in range(n_rows)
        ],
    }


def test_index_extract_metadata_uses_16_market_close_edt():
    """Latest row 2024-06-28 sits in EDT. 16:00 US/Eastern → UTC = 20:00. Sprint 043."""
    meta = alphavantage_index_extract_metadata(_canned_index_daily(n_rows=5))
    assert meta.rows_written == 5
    assert meta.value_time.year == 2024
    assert meta.value_time.month == 6
    assert meta.value_time.day == 28
    assert meta.value_time.hour == 20
    assert meta.value_time.minute == 0
    assert (meta.known_at - meta.value_time).total_seconds() == 60.0


def test_index_extract_metadata_raises_on_empty_data():
    with pytest.raises(AlphaVantageResponseError, match="no non-empty 'data' list"):
        alphavantage_index_extract_metadata({"symbol": "VIX", "data": []})


def test_index_extract_metadata_raises_on_missing_data_key():
    with pytest.raises(AlphaVantageResponseError, match="no non-empty 'data' list"):
        alphavantage_index_extract_metadata({"symbol": "VIX"})


def test_index_extract_metadata_raises_on_row_without_date():
    with pytest.raises(AlphaVantageResponseError, match="missing 'date' field"):
        alphavantage_index_extract_metadata({"symbol": "VIX", "data": [{"close": "12.5"}]})


# Macro extractor (Sprint 045) ---------------------------------------------


def _canned_macro(n_rows: int = 3) -> dict:
    return {
        "name": "Consumer Price Index",
        "interval": "monthly",
        "unit": "index 1982-1984=100",
        "data": [{"date": f"2024-{6 - i:02d}-01", "value": f"{300.0 + i}"} for i in range(n_rows)],
    }


def test_macro_extract_metadata_uses_latest_row_date():
    """Latest row 2024-06-01 sits in EDT; midnight local -> 04:00 UTC. Sprint 045."""
    meta = alphavantage_macro_extract_metadata(_canned_macro(n_rows=5))
    assert meta.rows_written == 5
    assert meta.value_time.year == 2024
    assert meta.value_time.month == 6
    assert meta.value_time.day == 1
    assert meta.value_time.hour == 4  # 00:00 EDT = 04:00 UTC
    assert meta.known_at == meta.value_time


def test_macro_extract_metadata_raises_on_empty_data():
    with pytest.raises(AlphaVantageResponseError, match="no non-empty 'data' list"):
        alphavantage_macro_extract_metadata({"name": "CPI", "data": []})


def test_macro_extract_metadata_raises_on_missing_data_key():
    with pytest.raises(AlphaVantageResponseError, match="no non-empty 'data' list"):
        alphavantage_macro_extract_metadata({"name": "CPI"})


def test_macro_extract_metadata_raises_on_row_without_date():
    with pytest.raises(AlphaVantageResponseError, match="missing 'date' field"):
        alphavantage_macro_extract_metadata({"name": "CPI", "data": [{"value": "300.0"}]})


# Put/call ratio extractor (Sprint 046) ------------------------------------


def test_pcr_extract_metadata_parses_date_and_value():
    """Sprint 046: HISTORICAL_PUT_CALL_RATIO response's date parsed as EDT midnight."""
    meta = alphavantage_put_call_ratio_extract_metadata(
        {
            "symbol": "SPY",
            "date": "2022-06-15",
            "put_call_ratio_full_chain": "1.16",
            "put_call_ratio_by_expiration": [],
        }
    )
    assert meta.rows_written == 1
    assert meta.value_time.year == 2022
    assert meta.value_time.month == 6
    assert meta.value_time.day == 15
    assert meta.value_time.hour == 4  # 00:00 EDT = 04:00 UTC
    assert meta.known_at == meta.value_time


def test_pcr_extract_metadata_raises_on_latest_date():
    """The 'latest' sentinel means the caller did not pin a real date; refuse."""
    with pytest.raises(AlphaVantageResponseError, match="no explicit date"):
        alphavantage_put_call_ratio_extract_metadata(
            {"symbol": "SPY", "date": "latest", "put_call_ratio_full_chain": "0.95"}
        )


def test_pcr_extract_metadata_raises_on_null_value():
    """Holidays return put_call_ratio_full_chain=null; extractor raises so the ingest
    caller can skip and let the aligned parquet's missing_mask surface the gap."""
    with pytest.raises(AlphaVantageResponseError, match="missing 'put_call_ratio_full_chain'"):
        alphavantage_put_call_ratio_extract_metadata(
            {"symbol": "SPY", "date": "2024-06-19", "put_call_ratio_full_chain": None}
        )
