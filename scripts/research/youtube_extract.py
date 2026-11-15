#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Eugeniu Ghelbur and contributors
# SPDX-License-Identifier: MIT
# Author: Eugeniu Ghelbur (AI Automation Engineer, AI Tooling Engineer, AI Educator), https://github.com/eugeniughelbur/obsidian-second-brain
# Questions or consulting: e.ghelbur@gmail.com | https://www.linkedin.com/in/eugeniu-ghelbur/ | More: https://theaioperator.io | https://x.com/eugeniu_ghelbur
"""/youtube [url] [--summary] [--visual] - capture or summarize a YouTube video.

Default (Method A capture): a **verbatim** note - full description, the timestamped
caption transcript grouped under the description's official chapter markers (or
computed caption-stream sections), the manual-vs-auto caption track recorded, and a
content_hash for drift detection. No LLM call; the transcript and description are
kept as evidence. Free: youtube-transcript-api (no key) + oEmbed (no key); the Data
API (YOUTUBE_API_KEY) adds the full description, view counts and comments.

--summary: the older behavior - LLM-summarize the transcript via Gemini/Grok into
TL;DR / Key Points / Notable Quotes / ..., saved as `type: youtube`.

--visual (summary mode): also download the video and extract one frame per scene
change (ffmpeg scene detection, via lib/video_frames.py).

Default save location: Research/YouTube/ (per vault.SUBFOLDERS).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .lib import config, grok, vault, video_frames, youtube

# Frames the visual layer reads by default. Kept modest: each frame is an image
# Claude reads, so cost scales with count. Override with --max-frames.
DEFAULT_VISUAL_MAX_FRAMES = 24

SUMMARIZE_PROMPT = """You are summarizing a YouTube video for a knowledge vault. The note will be read by future agent (an AI), not by a human. Optimize for AI retrieval.

VIDEO TITLE: {title}
CHANNEL: {channel}
PUBLISHED: {published}

TRANSCRIPT (first {tx_chars} chars):
\"\"\"
{transcript}
\"\"\"

{comments_section}

Produce EXACTLY this structure (markdown):

## TL;DR
[2-3 sentences capturing the core thesis or value of the video.]

## Key Points
- [Specific concrete claim, idea, or method from the video]
- [...continue for 5-12 bullets covering the actual substance, not filler]

## Notable Quotes
- "[Verbatim quote]" - [if you can locate it; max 5 quotes]

## Themes & Topics
[2-3 sentences naming the broader themes / domains this video touches]

## Comment Sentiment
[If comments were provided: 1-2 sentence summary of audience reaction. Note dominant praise, criticism, or question patterns. If no comments provided, write "No comments available."]

## Worth Following Up On
- [Specific things mentioned that would be worth a deeper /research call later]

Rules:
- Be specific. "Talks about AI" is useless to future agent. "Argues that LLM context windows over 1M tokens degrade reasoning quality after 200k tokens" is useful.
- Don't pad. If a section is genuinely thin, write one bullet and move on.
- Don't add commentary outside this structure.
"""


def _fmt_ts(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _extract_visual(video_id: str, title: str, max_frames: int) -> dict | None:
    """Download the video, extract scene-change frames, copy hero frames into the vault.

    Returns {frame_dir, frames, hero_rel_paths, count} or None if the visual layer
    could not run (missing binaries, download failure). Never raises - the visual
    layer is additive; transcript summary still saves on its own.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    work_dir = Path(tempfile.mkdtemp(prefix=f"youtube-visual-{video_id}-"))
    try:
        print("[/youtube] Downloading video for scene extraction...", file=sys.stderr)
        dl = video_frames.download_video(url, work_dir)
        print("[/youtube] Extracting scene-change frames...", file=sys.stderr)
        frames = video_frames.extract_scene_change(
            dl["video_path"], work_dir / "frames", max_frames=max_frames
        )
        if not frames:
            return None
        hero = video_frames.select_hero_frames(frames)

        # Persist hero frames into the vault so the embeds survive; the full set
        # stays in work_dir for Claude to read this session.
        date = datetime.now().strftime("%Y-%m-%d")
        slug = vault.slugify(title) or "untitled"
        att_dir = vault.VAULT_PATH / vault.SUBFOLDERS["youtube"] / "attachments" / f"{date}-{slug}"
        att_dir.mkdir(parents=True, exist_ok=True)
        hero_rel: list[tuple[str, float]] = []
        for i, f in enumerate(hero):
            dest = att_dir / f"hero_{i:02d}.jpg"
            shutil.copy2(f["path"], dest)
            rel = dest.relative_to(vault.VAULT_PATH).as_posix()
            hero_rel.append((rel, f["timestamp_seconds"]))

        return {
            "frame_dir": str(work_dir / "frames"),
            "frames": frames,
            "hero_rel": hero_rel,
            "count": len(frames),
            "source": frames[0].get("source", "scene-change"),
        }
    except video_frames.FrameError as e:
        print(f"[/youtube] Visual layer skipped: {e}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001 - visual layer must never break the summary
        print(f"[/youtube] Visual layer error ({type(e).__name__}): {e}", file=sys.stderr)
        return None


def _canonical(body: str) -> str:
    """Canonical text for content_hash drift detection (CRLF->LF, list markers,
    whitespace collapsed) - the same shape the vault's raw captures use."""
    t = body.replace("\r\n", "\n").replace("\ufeff", "")
    t = re.sub(r"^[ \t]*[*+][ \t]+", "- ", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()


def build_capture_note(*, video_id: str, title: str, channel: str, published: str,
                       duration: str, description: str, transcript_info: dict | None,
                       today: str, url: str) -> tuple[dict, str]:
    """Build the Method A capture note: verbatim description + transcript grouped
    by official chapters (or by computed caption-stream sections). Pure - no I/O -
    so it is unit-testable."""
    kind = (transcript_info or {}).get("kind")
    chapters = youtube.parse_chapters(description)
    lead = (f"> Source: YouTube video by {channel}, published {published}, duration {duration}, "
            f"{url}. Captured {today}. ")
    lines: list[str] = []
    if transcript_info:
        if chapters:
            sections = youtube.sections_from_chapters(transcript_info["segments"], chapters)
            basis = "the official chapter markers from the description"
        else:
            sections = youtube.compute_sections(transcript_info["segments"])
            basis = "section timestamps computed from the caption stream"
        lead += (f"Body is the {kind or 'unknown'} caption transcript with {basis}. Video description "
                 "and transcript retained verbatim; caption garbles are preserved.")
        for sec in sections:
            if not sec["texts"]:
                continue
            stamp = youtube.seconds_to_timestamp(sec["start"])
            header = f"### {stamp} - {sec['title']}" if sec.get("title") else f"### {stamp}"
            lines.append(header)
            lines.append("")
            lines.append(" ".join(sec["texts"]).strip())
            lines.append("")
    else:
        lead += "No caption transcript was available; the body is the video description only."

    body = (
        f"\n{lead}\n\n"
        f"## Video description (verbatim)\n\n{description.strip() or '(no description available)'}\n\n"
        f"## Transcript\n\n" + ("\n".join(lines).rstrip() if lines else "(no captions available)") + "\n"
    )
    fm = {
        "title": title,
        "date": today,
        "type": "source",
        "tags": ["source", "transcript", "video"],
        "source_url": url,
        "source_type": "video",
        "content_hash": hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:16],
        "capture_scope": "full-local",
        "source_quality": "medium",
        "author": channel,
        "channel": channel,
        "published": published,
        "duration": duration,
        "ai-first": True,
    }
    return fm, body


def _run_capture(video_id: str) -> int:
    """Method A capture: verbatim transcript + description + chapters, no LLM."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[/youtube] Capturing video {video_id} (Method A)...", file=sys.stderr)
    meta = youtube.get_video_metadata(video_id) or {}
    desc_source = "youtube-data-api" if meta.get("description_full") else "none"

    def _fill(src: dict | None) -> None:
        for k, v in (src or {}).items():
            if v and not meta.get(k):
                meta[k] = v

    # Method A needs the description (it carries the chapters). Prefer the
    # TranscriptAPI metadata call when TRANSCRIPTAPI_KEY is set (richest),
    # then the free watch page; oEmbed covers title/channel with no key.
    if not meta.get("description_full"):
        tm = youtube.get_transcriptapi_metadata(video_id)
        if tm and tm.get("description_full"):
            desc_source = "transcriptapi"
        _fill(tm)
    if not meta.get("title") or not meta.get("channel"):
        _fill(youtube.get_oembed(video_id))
    if not meta.get("description_full"):
        wp = youtube.get_watch_page_meta(video_id)
        if wp and wp.get("description_full"):
            desc_source = "watch-page"
        _fill(wp)
    title = meta.get("title") or f"Video {video_id}"
    channel = meta.get("channel") or "(unknown channel)"
    published = meta.get("published_at") or "(unknown date)"
    duration = meta.get("duration") or ""
    description = meta.get("description_full") or meta.get("description") or ""
    tg = youtube.get_transcript_segments(video_id)
    if not tg and not description:
        print("❌ Could not fetch a transcript or description. Is the video public and does it "
              "have captions? A YOUTUBE_API_KEY supplies the description when captions are absent.",
              file=sys.stderr)
        return 1
    today = datetime.now().strftime("%Y-%m-%d")
    fm, body = build_capture_note(
        video_id=video_id, title=title, channel=channel, published=published,
        duration=duration, description=description, transcript_info=tg, today=today, url=url,
    )
    path = vault.write_note("youtube", f"{title} ({channel})", fm, body)
    print(body)
    vault.print_save_links(path)
    vault.append_to_log(f"youtube capture on \"{title}\" - saved to {path.name}")
    kind = tg["kind"] if tg else "none"
    print(f"---\n[capture: {kind} captions · {len(tg['segments']) if tg else 0} segments · "
          f"description {len(description)} chars via {desc_source} · "
          f"chapters: {len(youtube.parse_chapters(description))}]",
          file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="/youtube", add_help=False)
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("--visual", action="store_true",
                        help="download video + extract scene-change frames for Claude to read (summary mode only)")
    parser.add_argument("--summary", action="store_true",
                        help="LLM-summarize instead of capturing the Method A verbatim note")
    parser.add_argument("--max-frames", type=int, default=DEFAULT_VISUAL_MAX_FRAMES,
                        help=f"cap on frames the visual layer reads (default {DEFAULT_VISUAL_MAX_FRAMES})")
    args = parser.parse_args(argv[1:])

    if not args.url.strip():
        print("Usage: /youtube <video-url-or-id> [--summary] [--visual] [--max-frames N]", file=sys.stderr)
        return 2

    try:
        video_id = youtube.parse_video_id(args.url.strip())
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    # Default is the Method A capture: verbatim transcript + description + chapters,
    # no LLM call. `--summary` opts into the older transcript-grounded summary.
    if not args.summary:
        if args.visual:
            print("[/youtube] --visual applies to --summary; ignoring it in capture mode.", file=sys.stderr)
        return _run_capture(video_id)

    print(f"[/youtube] Extracting video {video_id}...", file=sys.stderr)

    transcript = youtube.get_transcript(video_id)
    metadata = youtube.get_video_metadata(video_id)
    comments = youtube.get_top_comments(video_id, max_results=15)

    if not transcript and not metadata:
        print("❌ Could not fetch transcript or metadata. Is the video public and does it have captions?", file=sys.stderr)
        return 1

    title = (metadata or {}).get("title") or f"Video {video_id}"
    channel = (metadata or {}).get("channel") or "(unknown channel)"
    published = (metadata or {}).get("published_at") or "(unknown date)"

    # Visual layer (opt-in). Run before the summary so failures surface early.
    visual = _extract_visual(video_id, title, args.max_frames) if args.visual else None

    if transcript:
        # ~120k tokens. Gemini 1M-context flash models take full interview
        # transcripts (3h video ~ 400k chars) with headroom; the old 24k cap
        # silently discarded 90%+ of long videos.
        TX_LIMIT = config.get_optional_int("YOUTUBE_TX_LIMIT", 480000)
        tx_truncated = transcript[:TX_LIMIT]
        tx_note = "" if len(transcript) <= TX_LIMIT else f"\n\n[Transcript truncated at {TX_LIMIT} chars from total {len(transcript)} chars]"
    else:
        tx_truncated = "(transcript not available)"
        tx_note = ""

    comments_section = ""
    if comments:
        comments_section = "TOP COMMENTS (relevance order):\n"
        for c in comments[:15]:
            comments_section += f"- {c['author']} ({c['like_count']} 👍): {c['text'][:200]}\n"

    prompt = SUMMARIZE_PROMPT.format(
        title=title,
        channel=channel,
        published=published,
        tx_chars=len(tx_truncated),
        transcript=tx_truncated + tx_note,
        comments_section=comments_section,
    )

    # Prefer Gemini for the summary when its key is set (generous free tier),
    # fall back to Grok - transparently, since gemini.call mirrors grok.call's
    # return shape. No Gemini key = exactly the old Grok-only behavior.
    result = None
    summarizer = "Grok"
    if os.environ.get("GEMINI_API_KEY", "").strip():
        print("[/youtube] Summarizing via Gemini (free tier)...\n", file=sys.stderr)
        try:
            from .lib import gemini
            result = gemini.call(prompt, command="youtube", max_output_tokens=3000)
            summarizer = "Gemini"
        except Exception as e:  # noqa: BLE001 - fall back to Grok on any Gemini failure
            print(f"[/youtube] Gemini failed ({e}); falling back to Grok...", file=sys.stderr)
    if result is None:
        print("[/youtube] Summarizing via Grok...\n", file=sys.stderr)
        try:
            result = grok.call(prompt, command="youtube", max_output_tokens=3000)
        except Exception as e:
            print(f"\n❌ /youtube summarize failed: {e}", file=sys.stderr)
            return 1

    print(f"# {title}")
    print(f"**Channel:** {channel} · **Published:** {published}")
    print(f"**URL:** https://www.youtube.com/watch?v={video_id}\n")
    print(result["text"])

    # AI-first save
    now = datetime.now()
    preamble = (
        f"For future agent: This note is a transcript-grounded summary of YouTube video \"{title}\" "
        f"by {channel} (published {published}), processed on {now.strftime('%Y-%m-%d %H:%M')}. "
        f"Transcript was extracted via youtube-transcript-api and summarized via {summarizer}. "
        f"Quotes are sourced from the transcript verbatim where attributed. Use Worth Following Up On bullets to spawn deeper research."
    )
    if visual:
        preamble += (
            f" Visual layer: {visual['count']} keyframes were extracted via ffmpeg "
            f"{visual['source']} detection; the Visual notes section is Claude's own reading of those frames."
        )
    fm = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "type": "youtube",
        "video-id": video_id,
        "video-url": f"https://www.youtube.com/watch?v={video_id}",
        "title": title,
        "channel": channel,
        "channel-id": (metadata or {}).get("channel_id", ""),
        "published": published,
        "view-count": (metadata or {}).get("view_count"),
        "like-count": (metadata or {}).get("like_count"),
        "comment-count": (metadata or {}).get("comment_count"),
        "duration": (metadata or {}).get("duration"),
        "visual": bool(visual),
        "frame-count": visual["count"] if visual else None,
        "tags": ["research", "youtube"] + ((metadata or {}).get("tags") or [])[:5],
        "cost-usd": round(result["cost_usd"], 4),
        "ai-first": True,
    }
    note_body = (
        f"## For future agent\n\n{preamble}\n\n"
        f"## Video\n\n"
        f"- **Title:** {title}\n"
        f"- **Channel:** {channel}\n"
        f"- **Published:** {published}\n"
        f"- **URL:** https://www.youtube.com/watch?v={video_id}\n\n"
        f"## Summary\n\n{result['text']}\n"
    )
    if visual:
        note_body += "\n" + _visual_note_section(visual)

    path = vault.write_note("youtube", title, fm, note_body)
    vault.print_save_links(path)
    vault.append_to_log(f"youtube on \"{title}\" - saved to {path.name}")

    if visual:
        _print_frames_for_claude(path, visual)

    print(
        f"---\n[cost: ${result['cost_usd']:.4f} · transcript: {len(transcript) if transcript else 0} chars"
        f" · comments: {len(comments)}"
        + (f" · frames: {visual['count']}" if visual else "")
        + "]",
        file=sys.stderr,
    )
    return 0


def _visual_note_section(visual: dict) -> str:
    """Hero frame embeds + a pending marker for Claude to fill the visual reading."""
    lines = [
        "## Visual timeline",
        "",
        f"Key frames from ffmpeg {visual['source']} detection "
        f"({visual['count']} extracted). Representative frames embedded below:",
        "",
    ]
    for rel, ts in visual["hero_rel"]:
        lines.append(f"![[{rel}]]")
        lines.append(f"*{_fmt_ts(ts)}*")
        lines.append("")
    lines += [
        "## Visual notes",
        "",
        "<!-- CLAUDE: read the keyframes listed in the FRAMES-FOR-CLAUDE block the "
        "script printed, then replace this comment with visual analysis keyed by "
        "timestamp - on-screen text, code, diagrams, UI, b-roll, scene transitions. "
        "Cross-reference the transcript and Summary above; do not restate the audio. -->",
        "",
    ]
    return "\n".join(lines)


def _print_frames_for_claude(note_path: Path, visual: dict) -> None:
    """Emit a machine-readable block telling Claude which frames to read and which
    note to update. Claude reads the frames with its own vision, then edits the
    note's Visual notes section."""
    payload = {
        "note_path": str(note_path),
        "frame_dir": visual["frame_dir"],
        "instruction": (
            "Read each frame below (they are local JPGs), then Edit the note at "
            "note_path: replace the <!-- CLAUDE: ... --> comment in the '## Visual "
            "notes' section with a concise, timestamp-keyed visual reading. Focus on "
            "what the frames add over the transcript: on-screen text/code, diagrams, "
            "UI, demos, b-roll, scene transitions."
        ),
        "frames": [
            {"timestamp": _fmt_ts(f["timestamp_seconds"]), "path": f["path"]}
            for f in visual["frames"]
        ],
    }
    print("\n=== FRAMES-FOR-CLAUDE ===", file=sys.stderr)
    print(json.dumps(payload, indent=2), file=sys.stderr)
    print("=== END FRAMES-FOR-CLAUDE ===", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
