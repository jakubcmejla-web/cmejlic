# yt-transcripts

Turns YouTube videos into readable Markdown (title, channel, chapters, description and a
timestamped transcript) so Claude can "watch" them by reading `transcripts/<video-id>.md`.

## How to add a video

**Option A: from the GitHub website or app**
Actions → *Fetch YouTube transcripts* → **Run workflow** → paste one or more links.

**Option B: edit `requests.txt`**
Add a link on a new line and commit. The workflow runs on its own.

**Option C: ask Claude**
Give Claude the link. With GitHub connected, Claude can start the workflow and read the result.

After about a minute the file appears in `transcripts/`.

## If YouTube blocks it

YouTube sometimes refuses requests from GitHub's servers ("Sign in to confirm you're not a bot").
In that case the file is still saved, but it says no transcript was fetched. Fix:

1. Install the "Get cookies.txt LOCALLY" browser extension and export your youtube.com cookies.
2. In the repo: Settings → Secrets and variables → Actions → New secret, name it `YT_COOKIES`, and paste the file contents.

Use a throwaway Google account for this if you can.

## Run locally

```bash
pip install -r requirements.txt
python fetch_transcript.py https://www.youtube.com/watch?v=VIDEO_ID
```
