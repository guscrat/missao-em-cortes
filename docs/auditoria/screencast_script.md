# Screencast script: YouTube API Services audit

**Project:** `missao-em-cortes-publisher` · **Scope:** `https://www.googleapis.com/auth/youtube.upload`
**Tool:** Missão em Cortes (`scripts/09_upload.py`, demo mode `--demo=<step> --lang=en`)
**Target length:** 4–6 minutes · **Language:** English (narration or on-screen text)

## Before you hit record (not part of the video)

1. Prepare the test clip. This runs locally and sends nothing to YouTube:
   `powershell -ExecutionPolicy Bypass -File scripts\demo_auditoria.ps1 -Preparar`
   (optional: `-Stem <stem> -Bloco N -Segundos 15`). It cuts a 10–20 s clip from a finished video and copies its thumbnail to `state/demo_auditoria/`.
2. In the browser, sign in to the Google account that owns the channel (UCRJDgbBEndOdbNaiwzFju2g). Close other tabs.
3. Make the terminal font large (≥ 16 pt) and maximize it. Hide anything personal (bookmarks, notifications).
4. Open YouTube Studio in a second tab, on **Content**, but leave it out of view.

## Recording

Start recording, then run:
`powershell -ExecutionPolicy Bypass -File scripts\demo_auditoria.ps1`
The script pauses before every step, and nothing is uploaded until you press Enter at step 3.

| # | What is on screen | What to say / show |
|---|---|---|
| 0 | Intro panel: tool name, Google Cloud project, scope, list of steps | "This is Missão em Cortes, our internal tool that publishes clips of livestreams on our own YouTube channel. It uses the YouTube Data API with the youtube.upload scope only." |
| 1 | **Upload plan**: file, title, description, tags, thumbnail, `publishAt` (next slot), and the JSON body of `videos.insert` | "Before uploading, the tool shows the plan. In production every clip is uploaded as private with `status.publishAt`, so YouTube publishes it automatically at our daily slot. Source credit always goes in the description." Hold on the JSON for ~3 s. |
| 2 | **OAuth**: the old token is revoked, the browser opens Google's consent screen | Show the app name and the requested permission ("Manage your YouTube videos"). Pick the channel account, click **Allow**. Back in the terminal, show the "Granted scopes" line. "The token is stored locally and only used to upload to our own channel." |
| 3 | **Upload**: progress, then the `videos.insert` response with `id`, `uploadStatus`, `privacyStatus` | "This is a 15-second TEST clip, uploaded as private. The title starts with [TEST] and the description says it will not be published." |
| 4 | **Thumbnail + metadata**: `thumbnails.set` returns the thumbnail URL; `videos.update` is either run or skipped with the reason | If skipped: "Our project only requests youtube.upload, which does not cover videos.update. All metadata (title, description, tags, category, language) is set in the insert call itself, and the thumbnail through thumbnails.set." |
| 5 | **Confirmation**: video ID, uploadStatus, privacyStatus, thumbnail set, Studio link | "The API confirms the upload. Now let's check the result in YouTube Studio." |
| 6 | **YouTube Studio** (switch to the browser) | Refresh **Content**; show the new `[TEST]` video at the top, with the custom thumbnail. Hover the visibility column: **Private (locked)**. Open the video's details page: title, description (source link), thumbnail, visibility. Optionally open the Studio link printed in step 5. |
| 7 | Closing | "Videos are only published on our own channel, on schedule, with source credit. Thank you." Stop recording. |

## Notes

- **Why "Private (locked)":** while the project is not yet audited, YouTube locks every API upload as private. That is expected, and it is why this video is a test.
- **`publishAt` in the upload itself:** by default the test clip goes up private without `publishAt` (the plan in step 1 shows the real schedule). To send `publishAt` on the test upload too, record with `-Agendar`.
- **If a step fails,** the script stops with the HTTP code. Stop the recording, fix it, then record again from the start. Each attempt uploads one more test video (≈1,650 quota units).
- **After recording:** delete the test video in Studio if you like; the tool keeps no record of it besides `state/demo_auditoria/demo.json`.
