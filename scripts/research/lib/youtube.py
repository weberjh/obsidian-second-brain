# SPDX-FileCopyrightText: 2026 Eugeniu Ghelbur and contributors
# SPDX-License-Identifier: MIT
# Author: Eugeniu Ghelbur (AI Automation Engineer, AI Tooling Engineer, AI Educator), https://github.com/eugeniughelbur/obsidian-second-brain
# Questions or consulting: e.ghelbur@gmail.com | https://www.linkedin.com/in/eugeniu-ghelbur/ | More: https://theaioperator.io | https://x.com/eugeniu_ghelbur
"""YouTube transcript + Data API client.

Transcripts work without an API key (youtube-transcript-api).
Metadata + comments require YOUTUBE_API_KEY (free tier of YouTube Data API v3).
"""

import re
from typing import Any

from .config import YOUTUBE_API_KEY, get_optional

_KEY_PARAM = re.compile(r"(?i)\b(key|api_key|apikey|access_token)=[^&\s\"'<>]+")


def _api_error_summary(e: Exception) -> str:
    """A log-safe one-line summary of a Data API failure.

    googleapiclient's HttpError renders the full request URL, and that URL
    carries the API key as a query parameter. Report only the HTTP status and
    reason when the error has them; otherwise redact key-like parameters from
    the message before it is printed.
    """
    resp = getattr(e, "resp", None)
    status = getattr(resp, "status", None) if resp is not None else None
    if status is not None:
        reason = getattr(resp, "reason", None) or ""
        return f"{type(e).__name__}: HTTP {status} {reason}".rstrip()
    message = _KEY_PARAM.sub(r"\1=REDACTED", str(e))
    return f"{type(e).__name__}: {message}"


def parse_video_id(url_or_id: str) -> str:
    s = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            return m.group(1)
    raise ValueError(f"Could not extract YouTube video ID from: {url_or_id}")


def _transcript_languages() -> list[str]:
    """Preferred transcript languages, from TRANSCRIPT_LANGUAGES (comma-separated,
    e.g. "ja,en"). Read per call, not at import, so long-lived callers and tests
    can change it."""
    raw = get_optional("TRANSCRIPT_LANGUAGES", "en")
    return [lang.strip() for lang in raw.split(",") if lang.strip()]


def get_transcript(video_id: str) -> str | None:
    """Return concatenated transcript text, or None if unavailable.

    Tries TRANSCRIPT_LANGUAGES in order, then falls back to whatever language
    the video actually has. A preference miss is not "no captions" (issue
    #210): the old call used youtube-transcript-api's ('en',) default, so every
    non-English video looked caption-less even when its transcript was one
    argument away."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=_transcript_languages())
    except Exception as pref_err:
        try:
            first = next(iter(api.list(video_id)))
            print(f"[YouTube transcript: none of the preferred languages "
                  f"({','.join(_transcript_languages())}) available; using "
                  f"'{getattr(first, 'language_code', '?')}']")
            fetched = first.fetch()
        except Exception:
            print(f"[YouTube transcript unavailable: {type(pref_err).__name__}: {pref_err}]")
            return None
    return " ".join(seg.text for seg in fetched.snippets if seg.text).strip()


def get_video_metadata(video_id: str) -> dict[str, Any] | None:
    """Returns title, channel, published date, view/like/comment counts. None if no API key or error."""
    key = YOUTUBE_API_KEY()
    if not key:
        return None
    try:
        # An explicit transport timeout. Without one googleapiclient falls back to
        # httplib2's default of none, so a slow (not down) Data API blocks the whole
        # /youtube command - including the plain non-visual path - with no bound and
        # no way for the caller to recover. Matches lib/http.py's DEFAULT_TIMEOUT.
        import httplib2
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", developerKey=key, cache_discovery=False,
                   http=httplib2.Http(timeout=15))
        resp = yt.videos().list(part="snippet,statistics,contentDetails", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            return None
        item = items[0]
        sn = item.get("snippet", {})
        st = item.get("statistics", {})
        return {
            "title": sn.get("title"),
            "channel": sn.get("channelTitle"),
            "channel_id": sn.get("channelId"),
            "published_at": sn.get("publishedAt"),
            "description": sn.get("description", "")[:500],
            "description_full": sn.get("description", ""),
            "tags": sn.get("tags", []),
            "duration": item.get("contentDetails", {}).get("duration"),
            "view_count": int(st.get("viewCount", 0)),
            "like_count": int(st.get("likeCount", 0)) if "likeCount" in st else None,
            "comment_count": int(st.get("commentCount", 0)) if "commentCount" in st else None,
        }
    except Exception as e:
        print(f"[YouTube metadata error: {_api_error_summary(e)}]")
        return None


def get_top_comments(video_id: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Return top-rated comments. Empty list if no API key or comments disabled."""
    key = YOUTUBE_API_KEY()
    if not key:
        return []
    try:
        # An explicit transport timeout. Without one googleapiclient falls back to
        # httplib2's default of none, so a slow (not down) Data API blocks the whole
        # /youtube command - including the plain non-visual path - with no bound and
        # no way for the caller to recover. Matches lib/http.py's DEFAULT_TIMEOUT.
        import httplib2
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", developerKey=key, cache_discovery=False,
                   http=httplib2.Http(timeout=15))
        resp = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(max_results, 100),
            order="relevance",
            textFormat="plainText",
        ).execute()
        out = []
        for thread in resp.get("items", []):
            top = thread["snippet"]["topLevelComment"]["snippet"]
            out.append({
                "author": top.get("authorDisplayName"),
                "text": top.get("textDisplay"),
                "like_count": top.get("likeCount", 0),
                "published_at": top.get("publishedAt"),
            })
        return out
    except Exception as e:
        print(f"[YouTube comments error: {_api_error_summary(e)}]")
        return []


# --- Method A capture: timestamped transcript, oEmbed, chapters ---------------

# A chapter line: an optional list marker, an optional bracket, a timestamp, an
# optional separator, then the title. Accepts "0:00 Intro", "(0:00) Intro",
# "- (0:00) Intro" and "0:00 - Intro" - the shapes YouTube descriptions use.
_CHAPTER_LINE = re.compile(
    r"^\s*(?:[-*+\u2022]\s*)?[\(\[]?(\d{1,2}):(\d{2})(?::(\d{2}))?[\)\]]?\s*[-\u2013\u2014:.)]?\s*(.*\S)?\s*$"
)


def _extract_json_after(text: str, marker: str) -> dict | None:
    """Return the JSON object that follows ``marker`` in ``text``, brace-matching
    with string/escape awareness. None when the marker or a balanced object is
    absent. The watch page embeds several large JSON blobs this way."""
    import json as _json
    i = text.find(marker)
    if i < 0:
        return None
    j = text.find("{", i)
    if j < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for k in range(j, len(text)):
        c = text[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return _json.loads(text[j:k + 1])
                    except Exception:
                        return None
    return None


def get_watch_page_meta(video_id: str) -> dict[str, Any] | None:
    """Free, no-key metadata from the public watch page.

    Method A needs the **description** (it carries the chapter markers), and
    oEmbed does not provide one. The watch page embeds `ytInitialPlayerResponse`
    with title, author, description, view count, length and publish date, so a
    capture keeps its chapters and provenance without a `YOUTUBE_API_KEY`. Best
    effort: returns None when the page cannot be read or parsed.
    """
    try:
        import requests
        r = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = _extract_json_after(r.text, "ytInitialPlayerResponse")
        if not data:
            return None
        vd = data.get("videoDetails", {}) or {}
        mf = (data.get("microformat", {}) or {}).get("playerMicroformatRenderer", {}) or {}
        length = vd.get("lengthSeconds")
        try:
            duration = f"PT{int(length) // 60}M{int(length) % 60}S" if length else None
        except (TypeError, ValueError):
            duration = None
        return {
            "title": vd.get("title"),
            "channel": vd.get("author"),
            "description_full": vd.get("shortDescription", "") or "",
            "view_count": int(vd["viewCount"]) if str(vd.get("viewCount", "")).isdigit() else None,
            "published_at": mf.get("publishDate") or mf.get("uploadDate"),
            "duration": duration,
        }
    except Exception as e:  # noqa: BLE001 - a free fallback, never fatal
        print(f"[YouTube watch-page error: {type(e).__name__}: {e}]")
        return None


def seconds_to_timestamp(seconds: float) -> str:
    """0:00 / 12:34 / 1:02:03 - the shape the vault's section headers use."""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def get_transcriptapi_metadata(video_id: str) -> dict[str, Any] | None:
    """TranscriptAPI metadata (one paid call) when TRANSCRIPTAPI_KEY is set.

    A richer source than the free watch-page scrape: the full description (which
    carries the chapter markers), view/like counts, the publish date, the length
    and the caption-track list. Returns None when the key is unset or the call
    fails, so the caller falls through to the free paths.
    """
    key = get_optional("TRANSCRIPTAPI_KEY", "")
    if not key:
        return None
    try:
        import requests
        r = requests.get(
            "https://transcriptapi.com/api/v2/youtube/video/metadata",
            params={"video_url": f"https://www.youtube.com/watch?v={video_id}", "include": "details"},
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[TranscriptAPI metadata HTTP {r.status_code}]")
            return None
        d = r.json()
    except Exception as e:  # noqa: BLE001 - a keyed extra, never fatal
        print(f"[TranscriptAPI metadata error: {type(e).__name__}: {e}]")
        return None
    chan = d.get("channel", {}) or {}
    details = d.get("details", {}) or {}
    published = d.get("publishDate")
    if published:
        try:
            from datetime import datetime as _dt
            published = _dt.strptime(published, "%b %d, %Y").strftime("%Y-%m-%d")
        except Exception:  # noqa: BLE001 - keep whatever the API said
            pass
    views = None
    vm = re.search(r"[0-9][0-9,]*", d.get("viewCountText", "") or "")
    if vm:
        try:
            views = int(vm.group(0).replace(",", ""))
        except ValueError:
            views = None
    length = details.get("lengthSeconds")
    try:
        duration = f"PT{int(length) // 60}M{int(length) % 60}S" if length else None
    except (TypeError, ValueError):
        duration = None
    return {
        "title": d.get("title"),
        "channel": chan.get("name"),
        "channel_id": chan.get("channelId"),
        "description_full": d.get("description", "") or "",
        "view_count": views,
        "published_at": published,
        "duration": duration,
    }


def get_oembed(video_id: str) -> dict[str, Any] | None:
    """Free, no-key title/channel via YouTube's oEmbed endpoint. None on failure.

    oEmbed is the metadata source a Method A capture can always reach: it needs
    no API key, which is what lets a capture still carry an author and title when
    YOUTUBE_API_KEY is unset (the Data API path then supplies the description)."""
    try:
        import requests
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        return {
            "title": d.get("title"),
            "channel": d.get("author_name"),
            "author_url": d.get("author_url"),
        }
    except Exception as e:  # noqa: BLE001 - oEmbed is a free fallback, never fatal
        print(f"[YouTube oEmbed error: {type(e).__name__}: {e}]")
        return None


def get_transcript_segments(video_id: str) -> dict[str, Any] | None:
    """Timestamped transcript segments plus the track kind, or None.

    Prefers a **manual** (human) caption track over an **auto-generated** one,
    and the configured TRANSCRIPT_LANGUAGES over any other, because which track
    a capture used is load-bearing evidence (garbles, speaker labels). Returns
    {"segments": [{"text", "start", "duration"}], "kind": "manual"|"auto",
    "language_code": str} or None when no captions are available.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    api = YouTubeTranscriptApi()
    prefs = [p.split("-")[0].lower() for p in _transcript_languages()]
    try:
        listing = list(api.list(video_id))
    except Exception as e:  # noqa: BLE001 - a caption-less video is a normal outcome
        print(f"[YouTube transcript unavailable: {type(e).__name__}: {e}]")
        return None
    if not listing:
        return None

    def rank(t: Any) -> tuple[int, int]:
        lang = (getattr(t, "language_code", "") or "").lower()
        pref = 0 if lang.split("-")[0] in prefs else 1
        manual = 0 if not getattr(t, "is_generated", False) else 1
        return (pref, manual)

    best = sorted(listing, key=rank)[0]
    try:
        fetched = best.fetch()
    except Exception as e:  # noqa: BLE001
        print(f"[YouTube transcript fetch failed: {type(e).__name__}: {e}")
        return None
    segments = [
        {
            "text": s.text,
            "start": float(s.start),
            "duration": float(getattr(s, "duration", 0.0) or 0.0),
        }
        for s in fetched.snippets
        if getattr(s, "text", "").strip()
    ]
    if not segments:
        return None
    return {
        "segments": segments,
        "kind": "auto" if getattr(best, "is_generated", False) else "manual",
        "language_code": getattr(best, "language_code", "") or "",
    }


def parse_chapters(description: str) -> list[dict[str, Any]]:
    """Parse YouTube chapter markers out of a video description.

    A chapter list is only honoured when it has at least three entries, the first
    at 0:00, and strictly increasing timestamps - YouTube's own rule, applied
    here so a stray "0:30" in prose is not mistaken for a chapter. Returns
    [{"seconds": int, "title": str}], empty when there is no valid list.
    """
    if not description:
        return []
    chapters: list[dict[str, Any]] = []
    for line in description.splitlines():
        m = _CHAPTER_LINE.match(line)
        if not m:
            continue
        a, b, c = m.group(1), m.group(2), m.group(3)
        secs = int(a) * 60 + int(b) if c is None else int(a) * 3600 + int(b) * 60 + int(c)
        chapters.append({"seconds": secs, "title": (m.group(4) or "").strip()})
    if len(chapters) < 3 or chapters[0]["seconds"] != 0:
        return []
    if any(chapters[i + 1]["seconds"] <= chapters[i]["seconds"] for i in range(len(chapters) - 1)):
        return []
    return chapters


def sections_from_chapters(segments: list[dict[str, Any]],
                           chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign each segment to the chapter whose window contains it."""
    out: list[dict[str, Any]] = []
    for ch in chapters:
        out.append({"start": float(ch["seconds"]), "title": ch["title"], "texts": []})
    for s in segments:
        idx = 0
        for i, ch in enumerate(chapters):
            if s["start"] >= ch["seconds"]:
                idx = i
            else:
                break
        out[idx]["texts"].append(s["text"])
    return out


def compute_sections(segments: list[dict[str, Any]], min_gap: float = 10.0,
                     min_len: float = 45.0) -> list[dict[str, Any]]:
    """Group caption segments into sections at natural pauses.

    Used when the description carries no chapter markers: a new section opens
    when the pause before a segment exceeds ``min_gap`` seconds and the current
    section is already at least ``min_len`` long. Deterministic, so a re-capture
    of the same video yields the same section boundaries.
    """
    if not segments:
        return []
    sections: list[dict[str, Any]] = []
    cur = {"start": segments[0]["start"], "title": "", "texts": []}
    last_end = segments[0]["start"]
    for s in segments:
        gap = s["start"] - last_end
        if cur["texts"] and gap >= min_gap and (last_end - cur["start"]) >= min_len:
            sections.append(cur)
            cur = {"start": s["start"], "title": "", "texts": []}
        cur["texts"].append(s["text"])
        last_end = s["start"] + s.get("duration", 0.0)
    sections.append(cur)
    return sections
