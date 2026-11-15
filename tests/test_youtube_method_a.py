"""`/youtube` Method A capture: verbatim transcript + description + chapters.

The old `/youtube` always LLM-summarized; the vault (and the parked rebuild)
want a **verbatim capture** instead - full description, timestamped transcript
grouped by the description's official chapter markers (or computed sections),
the manual/auto track recorded, no model in the loop. These tests pin the pure
pieces: chapter parsing (YouTube's own >=3, start-at-0:00, strictly-increasing
rule), section computation, and the capture note builder.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

DESC = """In this talk we cover shipping agents.

Chapters:
0:00 Intro
1:30 The loop
3:00 Shipping

#agents #llm
"""


def test_parse_chapters_reads_a_valid_list():
    from research.lib.youtube import parse_chapters

    ch = parse_chapters(DESC)
    assert ch == [
        {"seconds": 0, "title": "Intro"},
        {"seconds": 90, "title": "The loop"},
        {"seconds": 180, "title": "Shipping"},
    ]


def test_parse_chapters_rejects_short_or_nonzero_start():
    from research.lib.youtube import parse_chapters

    # Fewer than 3 entries: not a chapter list.
    assert parse_chapters("0:00 Intro\n1:00 Outro") == []
    # Does not start at 0:00.
    assert parse_chapters("0:10 A\n1:00 B\n2:00 C") == []


def test_parse_chapters_ignores_prose_timestamps():
    from research.lib.youtube import parse_chapters

    prose = "the talk runs 1:30:00 and there is a break at 0:45 somewhere"
    assert parse_chapters(prose) == []


def test_parse_chapters_handles_brackets_and_hours():
    from research.lib.youtube import parse_chapters

    d = "(0:00) Opening\n(1:02:03) Late section\n(2:00:00) End\ntrailing"
    assert parse_chapters(d) == [
        {"seconds": 0, "title": "Opening"},
        {"seconds": 3723, "title": "Late section"},
        {"seconds": 7200, "title": "End"},
    ]


def test_seconds_to_timestamp():
    from research.lib.youtube import seconds_to_timestamp

    assert seconds_to_timestamp(0) == "0:00"
    assert seconds_to_timestamp(95) == "1:35"
    assert seconds_to_timestamp(3725) == "1:02:05"


def test_sections_from_chapters_assigns_segments_by_time():
    from research.lib.youtube import parse_chapters, sections_from_chapters

    segs = [
        {"text": "a", "start": 0.0, "duration": 5},
        {"text": "b", "start": 10.0, "duration": 5},
        {"text": "c", "start": 95.0, "duration": 5},
        {"text": "d", "start": 200.0, "duration": 5},
    ]
    secs = sections_from_chapters(segs, parse_chapters(DESC))
    assert [s["title"] for s in secs] == ["Intro", "The loop", "Shipping"]
    assert secs[0]["texts"] == ["a", "b"]
    assert secs[1]["texts"] == ["c"]
    assert secs[2]["texts"] == ["d"]


def test_compute_sections_breaks_on_a_gap():
    from research.lib.youtube import compute_sections

    segs = [
        {"text": "one", "start": 0.0, "duration": 5},
        {"text": "two", "start": 60.0, "duration": 5},
        {"text": "three", "start": 120.0, "duration": 5},
        # long pause > 10s and current section >= 45s -> new section
        {"text": "four", "start": 200.0, "duration": 5},
    ]
    secs = compute_sections(segs)
    assert len(secs) >= 2
    assert secs[0]["texts"][0] == "one"
    assert "four" in secs[-1]["texts"]


def test_parse_chapters_accepts_markdown_bullet_chapters():
    from research.lib.youtube import parse_chapters

    d = "*Key Moments*\n- (0:00) Guest Introduction\n- (2:21) BI Semantic Layers\n- (9:22) Why KGs Matter"
    assert parse_chapters(d) == [
        {"seconds": 0, "title": "Guest Introduction"},
        {"seconds": 141, "title": "BI Semantic Layers"},
        {"seconds": 562, "title": "Why KGs Matter"},
    ]


def test_transcriptapi_metadata_parses(monkeypatch):
    import requests
    from research.lib.youtube import get_transcriptapi_metadata

    payload = {
        "title": "How Semantic Layers Work",
        "publishDate": "Apr 22, 2026",
        "viewCountText": "12,507 views",
        "description": "Learn why an organization's ontology matters.\n\n0:00 Intro\n1:30 Middle\n3:00 End",
        "channel": {"channelId": "UCabc", "name": "ThoughtSpot"},
        "details": {"lengthSeconds": 3200},
    }
    fake = type("R", (), {"status_code": 200, "json": staticmethod(lambda: payload)})()
    monkeypatch.setattr(requests, "get", lambda *a, **k: fake)
    monkeypatch.setenv("TRANSCRIPTAPI_KEY", "sk_test")

    m = get_transcriptapi_metadata("abcdefghijk")
    assert m["title"] == "How Semantic Layers Work"
    assert m["channel"] == "ThoughtSpot"
    assert m["channel_id"] == "UCabc"
    assert m["description_full"].startswith("Learn why")
    assert m["view_count"] == 12507
    assert m["published_at"] == "2026-04-22"
    assert m["duration"] == "PT53M20S"


def test_transcriptapi_metadata_absent_without_key(monkeypatch):
    from research.lib.youtube import get_transcriptapi_metadata

    monkeypatch.delenv("TRANSCRIPTAPI_KEY", raising=False)
    assert get_transcriptapi_metadata("abcdefghijk") is None


def test_extract_json_after_handles_braces_in_strings():
    from research.lib.youtube import _extract_json_after

    text = 'noise ytInitialPlayerResponse = {"a": {"b": "}"}, "c": 1}; trailing'
    assert _extract_json_after(text, "ytInitialPlayerResponse") == {"a": {"b": "}"}, "c": 1}
    assert _extract_json_after("nothing here", "ytInitialPlayerResponse") is None


def test_build_capture_note_is_verbatim_and_chaptered():
    from research.youtube_extract import build_capture_note

    segs = [
        {"text": "welcome to the talk", "start": 0.0, "duration": 4},
        {"text": "here is the loop", "start": 95.0, "duration": 4},
        {"text": "now we ship", "start": 200.0, "duration": 4},
    ]
    fm, body = build_capture_note(
        video_id="abcdefghijk", title="Shipping Agents", channel="AI Engineer",
        published="2026-01-02", duration="PT5M", description=DESC,
        transcript_info={"segments": segs, "kind": "manual", "language_code": "en"},
        today="2026-11-15", url="https://www.youtube.com/watch?v=abcdefghijk",
    )
    assert fm["type"] == "source"
    assert fm["source_type"] == "video"
    assert fm["capture_scope"] == "full-local"
    assert fm["channel"] == "AI Engineer"
    assert len(fm["content_hash"]) == 16
    assert "manual caption transcript" in body
    assert "## Video description (verbatim)" in body
    # description preserved verbatim
    assert "In this talk we cover shipping agents." in body
    # official chapter markers used as section headers
    assert "### 0:00 - Intro" in body
    assert "### 1:30 - The loop" in body
    assert "### 3:00 - Shipping" in body
    assert "welcome to the talk" in body


def test_build_capture_note_falls_back_to_computed_sections():
    from research.youtube_extract import build_capture_note

    segs = [{"text": f"line {i}", "start": float(i) * 1.0, "duration": 0.8} for i in range(200)]
    fm, body = build_capture_note(
        video_id="abcdefghijk", title="T", channel="C", published="2026-01-02",
        duration="", description="no chapters here", transcript_info={
            "segments": segs, "kind": "auto", "language_code": "en"},
        today="2026-11-15", url="u",
    )
    assert "auto caption transcript" in body
    assert "computed from the caption stream" in body
    assert fm["content_hash"] != ""


def test_build_capture_note_description_only():
    from research.youtube_extract import build_capture_note

    fm, body = build_capture_note(
        video_id="abcdefghijk", title="T", channel="C", published="(unknown date)",
        duration="", description="only a description", transcript_info=None,
        today="2026-11-15", url="u",
    )
    assert "No caption transcript was available" in body
    assert "only a description" in body
