#!/usr/bin/env python3
"""Fetch YouTube transcripts + metadata and save them as Markdown in transcripts/.

URLs come from (in this order): command-line args, the URLS env var
(space/comma/newline separated) and requests.txt (one URL per line, # = comment).
Videos that already have a transcript file are skipped.
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "transcripts"
PREFERRED_LANGS = ["en", "cs", "sk", "de"]

ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def video_id(url: str) -> str | None:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    m = ID_RE.search(url)
    return m.group(1) if m else None


def collect_urls(argv: list[str]) -> list[str]:
    urls = list(argv)
    urls += re.split(r"[\s,]+", os.environ.get("URLS", ""))
    req = ROOT / "requests.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                urls.append(line)
    return [u for u in urls if u.strip()]


def ts(seconds: float) -> str:
    s = int(seconds)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def ydl_opts() -> dict:
    opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    cookies = os.environ.get("YT_COOKIES", "").strip()
    if cookies:
        path = ROOT / ".cookies.txt"
        path.write_text(cookies + "\n", encoding="utf-8")
        opts["cookiefile"] = str(path)
    return opts


def get_metadata(vid: str) -> dict:
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts()) as ydl:
            return ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False) or {}
    except Exception as e:  # noqa: BLE001
        print(f"  ! metadata failed: {e}", file=sys.stderr)
        return {}


def transcript_via_api(vid: str) -> tuple[list[tuple[float, str]], str] | None:
    """Primary method: youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        tlist = api.list(vid)
        available = list(tlist)
        if not available:
            return None
        try:
            t = tlist.find_transcript(PREFERRED_LANGS)
        except Exception:  # noqa: BLE001
            t = available[0]
        fetched = t.fetch()
        lines = [(s.start, s.text) for s in fetched]
        kind = "auto-generated" if t.is_generated else "manual"
        return lines, f"{t.language} ({t.language_code}, {kind})"
    except Exception as e:  # noqa: BLE001
        print(f"  ! transcript API failed: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return None


def transcript_via_ytdlp(info: dict) -> tuple[list[tuple[float, str]], str] | None:
    """Fallback: caption tracks listed by yt-dlp (json3 format)."""
    for source, kind in (("subtitles", "manual"), ("automatic_captions", "auto-generated")):
        tracks = info.get(source) or {}
        langs = [l for l in PREFERRED_LANGS if l in tracks] or list(tracks)
        for lang in langs:
            for fmt in tracks[lang]:
                if fmt.get("ext") != "json3":
                    continue
                try:
                    with urllib.request.urlopen(fmt["url"], timeout=30) as r:
                        data = json.load(r)
                    lines = []
                    for ev in data.get("events", []):
                        text = "".join(seg.get("utf8", "") for seg in ev.get("segs") or []).strip()
                        if text:
                            lines.append((ev.get("tStartMs", 0) / 1000, text))
                    if lines:
                        return lines, f"{lang} ({kind}, via yt-dlp)"
                except Exception as e:  # noqa: BLE001
                    print(f"  ! yt-dlp caption fetch failed: {e}", file=sys.stderr)
    return None


def group_paragraphs(lines: list[tuple[float, str]], every: float = 30.0) -> list[str]:
    """Merge caption fragments into ~30-second paragraphs with a timestamp each."""
    paras, cur, start = [], [], None
    for t, text in lines:
        text = " ".join(text.replace("\n", " ").split())
        if start is None:
            start = t
        if t - start >= every and cur:
            paras.append(f"[{ts(start)}] " + " ".join(cur))
            cur, start = [], t
        cur.append(text)
    if cur:
        paras.append(f"[{ts(start or 0)}] " + " ".join(cur))
    return paras


def process(vid: str) -> bool:
    out = OUT / f"{vid}.md"
    if out.exists():
        print(f"- {vid}: already done, skipping")
        return True
    print(f"- {vid}: fetching")
    info = get_metadata(vid)
    result = transcript_via_api(vid) or (transcript_via_ytdlp(info) if info else None)

    title = info.get("title") or vid
    md = [f"# {title}", ""]
    md.append(f"- URL: https://www.youtube.com/watch?v={vid}")
    for key, label in (("channel", "Channel"), ("upload_date", "Uploaded"),
                       ("duration_string", "Duration"), ("view_count", "Views")):
        if info.get(key):
            md.append(f"- {label}: {info[key]}")
    if result:
        md.append(f"- Transcript: {result[1]}")
    if info.get("chapters"):
        md += ["", "## Chapters", ""]
        md += [f"- [{ts(c['start_time'])}] {c.get('title', '')}" for c in info["chapters"]]
    if info.get("description"):
        md += ["", "## Description", "", info["description"].strip()]
    md += ["", "## Transcript", ""]
    if result:
        md += [p + "\n" for p in group_paragraphs(result[0])]
    else:
        md.append("_No transcript could be fetched (none available, or YouTube blocked the request)._")

    OUT.mkdir(exist_ok=True)
    out.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(f"  saved {out.relative_to(ROOT)} ({'ok' if result else 'NO TRANSCRIPT'})")
    return bool(result)


def main() -> int:
    ids, seen = [], set()
    for u in collect_urls(sys.argv[1:]):
        vid = video_id(u)
        if not vid:
            print(f"! not a YouTube URL: {u}", file=sys.stderr)
        elif vid not in seen:
            seen.add(vid)
            ids.append(vid)
    if not ids:
        print("No URLs given.")
        return 0
    failures = sum(not process(v) for v in ids)
    (ROOT / ".cookies.txt").unlink(missing_ok=True)
    print(f"Done: {len(ids) - failures} ok, {failures} without transcript.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
