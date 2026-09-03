"""Tests for the patent term adjustment normalizer in api/helpers.py.

The ODP /adjustment history bag runs to 60+ events on a normal prosecution
(15992176 returns 62), most of them docketing noise, so the normalizer caps it
and must always say how much history it did not return. Field names below are
the ones the live ODP endpoint returns, not the swagger's external $ref.
"""

from patent_filewrapper_mcp.api.helpers import (
    PTA_HISTORY_DEFAULT_CAP,
    normalize_term_adjustment,
)

_SUMMARY = {
    "applicantDayDelayQuantity": 28,
    "overlappingDayQuantity": 3,
    "ipOfficeAdjustmentDelayQuantity": 1,
    "cDelayQuantity": 0,
    "adjustmentTotalQuantity": 71,
    "bDelayQuantity": 5,
    "nonOverlappingDayDelayQuantity": 71,
    "aDelayQuantity": 71,
}


def _event(index: int) -> dict:
    return {
        "applicantDayDelayQuantity": 0,
        "eventDescriptionText": f"Event {index}",
        "eventSequenceNumber": float(index),
        "originatingEventSequenceNumber": 0.0,
        "ptaPTECode": "PTA",
        "ipOfficeDayDelayQuantity": 0,
        # Monotonic with index, so a higher sequence number is always a later date.
        "eventDate": f"2020-{(index // 28) + 1:02d}-{(index % 28) + 1:02d}",
    }


def _data(event_count: int) -> dict:
    return {
        **_SUMMARY,
        "patentTermAdjustmentHistoryDataBag": [_event(i) for i in range(event_count, 0, -1)],
    }


def test_summary_fields_are_flattened():
    result = normalize_term_adjustment(_data(1))

    assert result["adjustment"] == {
        "adjustment_total_days": 71,
        "a_delay_days": 71,
        "b_delay_days": 5,
        "c_delay_days": 0,
        "applicant_delay_days": 28,
        "overlapping_days": 3,
        "non_overlapping_delay_days": 71,
        "ip_office_adjustment_delay_days": 1,
    }
    event = result["history"][0]
    assert set(event) == {
        "event_date", "description", "event_sequence_number",
        "originating_event_sequence_number", "pta_pte_code",
        "applicant_delay_days", "ip_office_delay_days",
    }
    assert event["pta_pte_code"] == "PTA"


def test_long_history_is_capped_with_counts_and_note():
    result = normalize_term_adjustment(_data(62))

    assert result["history_returned"] == PTA_HISTORY_DEFAULT_CAP == 20
    assert result["history_total"] == 62
    assert result["history_truncated"] is True
    assert len(result["history"]) == 20
    assert "20 most recent of 62" in result["history_note"]
    assert "max_events" in result["history_note"]


def test_short_history_is_not_truncated():
    result = normalize_term_adjustment(_data(5))

    assert result["history_returned"] == 5
    assert result["history_total"] == 5
    assert result["history_truncated"] is False
    assert "history_note" not in result


def test_cap_keeps_the_most_recent_events_whatever_order_the_api_used():
    data = _data(30)
    # Scramble: the API returns newest-first, but the cap must not depend on it.
    data["patentTermAdjustmentHistoryDataBag"].sort(key=lambda e: e["eventSequenceNumber"])

    result = normalize_term_adjustment(data, max_events=3)

    dates = [e["event_date"] for e in result["history"]]
    assert dates == sorted(dates, reverse=True)
    assert result["history"][0]["event_sequence_number"] == 30.0
    assert result["history_total"] == 30


def test_max_events_floor_of_one():
    result = normalize_term_adjustment(_data(10), max_events=0)

    assert result["history_returned"] == 1
    assert result["history_truncated"] is True


def test_missing_adjustment_data_is_a_note_not_an_error():
    for empty in ({}, None, "not-a-dict"):
        result = normalize_term_adjustment(empty)
        assert result["history"] == []
        assert result["history_total"] == 0
        assert result["adjustment"]["adjustment_total_days"] is None
        assert "no patentTermAdjustmentData" in result["note"]


def test_non_dict_history_entries_are_skipped():
    data = _data(2)
    data["patentTermAdjustmentHistoryDataBag"].append("junk")

    result = normalize_term_adjustment(data)

    assert result["history_total"] == 2
