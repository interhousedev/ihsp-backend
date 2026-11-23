---
name: edu-video
description: Use for producing lesson videos for the LMS: script, TTS voiceover, HyperFrames render, captions (burned and VTT), accessibility and upload; not for editing app UI
---

# Educational video

Render with skill://hyperframes and skill://hyperframes-cli (`npx hyperframes`, 1920×1080, 30 fps); reuse visuals via skill://hyperframes-registry; audio and images via skill://media-use. Render locally; put outputs under `temp-media/` (never in git).

## Standards

- Length 3–6 minutes (Guo, Kim & Rubin 2014). One idea, diagrams that grow, no bullet slides.
- WCAG 2.2: captions for prerecorded video, SC 1.2.2 (A); audio description, SC 1.2.5 (AA): narrate everything shown on screen so no separate description track is needed (https://www.w3.org/WAI/WCAG22/Understanding/captions-prerecorded).
- Captions: WebVTT (https://www.w3.org/TR/webvtt1/), ≤ 2 lines, ≤ 42 characters per line, timings from the real audio. Keep SRT only for export. Burn captions in too, because the LMS video block has no caption track yet; put the transcript in a text block.
- Interop: IMS Common Cartridge 1.3 (LMS import `/v1/lms/courses/import`), QTI 3.0 for test exchange (https://www.imsglobal.org/spec/qti/v3p0/oview), xAPI/cmi5 for activity data (https://xapi.com/cmi5/technical), H5P packages are supported as an LMS block.

## Voiceover (TTS)

| Option | uz | ru | Setup |
|---|---|---|---|
| Gemini `gemini-3.8-flash-tts` | Northern Uzbek listed | yes | `GEMINI_API_KEY` in a git-ignored file (`materials/dev-keys/secrets.env`) |
| VoiceLab `api.voicelab.uz/v1/tts` (`lison`) | Gulnoza, Lola, Sardor, Xurshid | yes | Bearer key with `tts:write`; 1 character = 1 credit; ≤ 5000 chars/request |
| macOS `say -v Milena` | no | yes | offline fallback, label it as synthetic |

Sources: https://ai.google.dev/gemini-api/docs/speech-generation, https://docs.voicelab.uz/api/tts. Never commit keys; read their terms before publishing generated voices.

## Steps

1. Script: ~130 words per minute; one sentence per caption cue.
2. TTS per sentence → measure with `ffprobe` → write the VTT from the real durations.
3. Build the HyperFrames composition with the audio and captions; `npx hyperframes check --json`; render MP4 (H.264, AAC).
4. Upload as `lms_video` and add it with `video_file` (skill://lms-publish).
