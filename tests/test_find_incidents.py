import sys
import json
import pytest

sys.path.insert(0, "..")
from tools.find_incidents import cluster_events, detect_shutdown_type


def _evt(time_str: str) -> dict:
    """Helper to build an event dict for checking clustering logic."""
    return {"time": time_str, "unit": "kernel", "message": "test"}


def test_cluster_events_empty():
    assert cluster_events([]) == []


def test_cluster_events_single():
    events = [_evt("2026-03-29T10:00:00+00:00")]
    assert cluster_events(events) == [events]


def test_cluster_events_under_limit():
    # 5 min apart -> 1 cluster
    events = [
        _evt("2026-03-29T10:00:00+00:00"),
        _evt("2026-03-29T10:05:00+00:00")
    ]
    assert cluster_events(events) == [events]


def test_cluster_events_exact_limit():
    # Exactly 10 min apart -> 1 cluster
    events = [
        _evt("2026-03-29T10:00:00+00:00"),
        _evt("2026-03-29T10:10:00+00:00")
    ]
    assert cluster_events(events) == [events]


def test_cluster_events_over_limit():
    # 10 min 1 sec apart -> 2 clusters
    e1 = _evt("2026-03-29T10:00:00+00:00")
    e2 = _evt("2026-03-29T10:10:01+00:00")
    
    assert cluster_events([e1, e2]) == [[e1], [e2]]


def test_cluster_events_realistic_pattern():
    # 3 events within 8 mins, 4th event 20 mins later
    e1 = _evt("2026-03-29T10:00:00+00:00")
    e2 = _evt("2026-03-29T10:04:00+00:00")
    e3 = _evt("2026-03-29T10:08:00+00:00")
    e4 = _evt("2026-03-29T10:28:00+00:00")
    
    clusters = cluster_events([e1, e2, e3, e4])
    
    assert len(clusters) == 2
    assert clusters[0] == [e1, e2, e3]
    assert clusters[1] == [e4]


def test_detect_shutdown_binary_message():
    """
    Ensure the parser does not crash when hitting kernel/journald lines 
    where MESSAGE is recorded as a raw binary int list instead of a string.
    Expected outcome: It skips the un-decodable line and assumes hard_lockup.
    """
    raw_line = json.dumps({
        "MESSAGE": [72, 101, 108, 108, 111],
        "__REALTIME_TIMESTAMP": "1000000000000000"
    })
    
    assert detect_shutdown_type(raw_line) == "hard_lockup"
