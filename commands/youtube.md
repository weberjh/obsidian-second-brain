---
description: Capture a YouTube video verbatim (description + transcript + chapters, Method A) or summarize it with --summary (Gemini/Grok). Add --summary --visual to also read the video's frames (scene detection)
category: research
triggers_en: ["summarize youtube", "youtube transcript", "extract video", "youtube to vault", "watch this video", "what's on screen in this video"]
triggers_de: ["YouTube zusammenfassen", "YouTube-Transkript", "Video auswerten", "YouTube in den Vault", "dieses Video ansehen", "was ist in diesem Video auf dem Bildschirm"]
triggers_es: ["resume este vídeo de youtube", "transcripción de youtube", "extrae este vídeo", "youtube al vault", "mira este vídeo", "qué se ve en este vídeo"]
triggers_pt: ["resuma este vídeo do youtube", "transcrição do youtube", "extraia este vídeo", "youtube para o vault", "assista a este vídeo", "o que aparece neste vídeo"]
triggers_zh: ["总结这个 YouTube 视频", "提取视频字幕", "把这个视频整理进知识库", "这个视频讲了什么", "看看视频画面里有什么"]
---

Use the obsidian-second-brain skill. Execute `/youtube [url] [--visual]`:

1. Resolve the YouTube URL or video ID from the user's argument. Accept any of: full URL (`https://www.youtube.com/watch?v=...`), `https://youtu.be/...`, `https://www.youtube.com/shorts/...`, or just the 11-character video ID. If no input given, ask: "Which YouTube video?"

2. Run the script from the skill root (its absolute path was given at session start as **Skill root**; substitute it for `SKILL_ROOT`):
   ```bash
   uv run --directory "SKILL_ROOT" -m scripts.research.youtube_extract "<url-or-id>"
   ```
   By default this produces a **Method A capture** - a verbatim record, not a summary:
   - the **full video description**, kept verbatim (method A shape);
   - the **timestamped caption transcript**, grouped under the description's **official chapter markers** when present, otherwise under sections computed from the caption stream;
   - which caption track was used (**manual** vs **auto-generated**) and the language code;
   - a `content_hash` for drift detection, and `type: source` frontmatter (the raw-capture schema), so the note is evidence a later agent can re-read.

   Free: `youtube-transcript-api` (no key) for the transcript, YouTube **oEmbed** (no key) for title/channel, and the public watch page (no key) for the description. The description is what carries the chapter markers, so it is fetched with a preference order: `YOUTUBE_API_KEY` (YouTube Data API, free tier) → `TRANSCRIPTAPI_KEY` (TranscriptAPI, one paid call, also gives counts/date/length and the caption-track list) → the watch-page scrape (free). Any one is enough for chapters.

   Add `--summary` when the user wants the video *digested* rather than *preserved* (a TL;DR and key points): the transcript is LLM-summarized via Gemini (`GEMINI_API_KEY`, free tier) or Grok, the older `type: youtube` note.
   ```bash
   uv run --directory "SKILL_ROOT" -m scripts.research.youtube_extract "<url-or-id>" --summary
   ```
   Add `--visual` **with `--summary`** when the user wants the video watched, not just transcribed (demos, whiteboards, slides, UI walkthroughs, b-roll, "what's on screen"). Optional `--max-frames N` caps frames (default 24):
   ```bash
   uv run --directory "SKILL_ROOT" -m scripts.research.youtube_extract "<url-or-id>" --summary --visual
   ```

3. What the default capture gives you, and why it matters:
   - **Description preserved verbatim** - it is source material (the chapters, links, and claims live in it); do not paraphrase it in the note.
   - **Chapters are the description's own chapter markers**, parsed by YouTube's rule (at least three, starting at `0:00`, strictly increasing). When the description has none, sections are computed from pauses in the caption stream and the note says so.
   - **The track kind is recorded** (`manual` or `auto`). Manual captions carry speaker labels; auto captions carry ASR garbles. A later agent reading the note needs to know which it has.
   - No model is in the loop, so nothing is invented or smoothed over.

4. Show the script output verbatim to the user.

5. **Default save behavior: saves automatically.** The capture is written to `Research/YouTube/YYYY-MM-DD - <title> (<channel>).md` with `type: source` frontmatter (`source_url`, `source_type: video`, `channel`, `published`, `duration`, `content_hash`, `capture_scope: full-local`). `--summary` instead writes a `type: youtube` note.

6. **If `--summary --visual` was used:** the script prints a `FRAMES-FOR-CLAUDE` JSON block (stderr) listing each keyframe with timestamp and local path, plus the saved note path. Do this:
   - Read each frame image with the read-files tool (they are local JPGs). This is your own vision doing the watching - no extra vision-API call.
   - Edit the saved note: replace the `<!-- CLAUDE: ... -->` comment in `## Visual notes` with a concise, timestamp-keyed reading of what the frames add over the transcript (on-screen text, code, diagrams, slides, UI, demos, b-roll). Cross-reference the Summary; do not restate the audio.
   - Keep the `## Visual timeline` hero-frame embeds intact.
   - If `--max-frames` is high, read the hero frames plus an even sample and say so in the note.

7. Plain English triggers for the capture: "transcribe this video", "save this video's transcript", "extract this YouTube link", "preserve this talk", or pasting a URL to keep. Triggers for `--summary`: "summarize this YouTube video", "what's in this video", "what did they say". When the ask is about what is *shown* (not said), use `--summary --visual`. When in doubt, capture: a capture can be summarized later, a summary cannot be turned back into a transcript.

8. If the video has no captions AND no description (no `YOUTUBE_API_KEY`), the script fails with a clear message - surface it. Suggest a `YOUTUBE_API_KEY`, `--summary --visual` (which can read the video without captions), or a different video.

9. If the user asks to research something mentioned in a summary's "Worth Following Up On" section, route that to `/research [topic]`.

---

**AI-first rule:** Every note created or updated by this command MUST follow `references/ai-first-rules.md` - `## For future agent` preamble, rich frontmatter (`type`, `date`, `tags`, `ai-first: true`, plus type-specific fields), recency markers per external claim, mandatory `[[wikilinks]]` for every person/project/concept referenced, sources preserved verbatim with URLs inline, and confidence levels where applicable. If that path does not resolve from your working directory, search upward for it; if you still cannot read it, say so before writing rather than producing a note that silently skips the rule. The vault is for future agent retrieval - not human reading.

**Anti-fabrication:** Search exhaustively before claiming any note, person, or file is absent - false absence is the most common failure mode - and never invent facts, entities, or dates (mark unknowns as `TBD`). See the anti-fabrication and search-completeness hard rules in `references/ai-first-rules.md`.

<!-- author-credit -->

---

From [obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain), created by Eugeniu Ghelbur (AI Automation Engineer, AI Tooling Engineer, AI Educator). Questions or consulting: [LinkedIn](https://www.linkedin.com/in/eugeniu-ghelbur/) or [e.ghelbur@gmail.com](mailto:e.ghelbur@gmail.com). More: [The AI Operator](https://theaioperator.io/?utm_source=github&utm_medium=file-credit) | [X](https://x.com/eugeniu_ghelbur) | [GitHub](https://github.com/eugeniughelbur). MIT license.
