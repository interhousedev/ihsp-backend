---
name: lms-html-widgets
description: Use for authoring or reviewing LMS HTML widget blocks: package layout, widget SDK, postMessage protocol, sandbox limits, upload
---

# LMS HTML widgets

An `html` lesson block shows an author-made HTML page in a sandboxed iframe. The author uploads one `.html` file or a
`.zip` with `index.html` at its root; learners open it, and a graded widget reports a score.

## Package

- `index.html` at the zip root (a single `.html` upload is stored as `index.html`). Relative paths only.
- Limits: 20 MiB upload, 60 MiB unpacked, 500 files. Absolute paths, `..`, symlinks and unknown file types are
  rejected (`lms-html-widget-invalid`). Allowed: html, css, js, mjs, json, svg, images, fonts, audio, video, txt, csv.
- Copy `ihsp-widget.js` and `ihsp-widget.css` from `iht-web/apps/lms/public/widget-sdk/` into the zip.

## Serving and trust boundary

- `POST /v1/lms/courses/{course_id}/html-widgets` (staff) stores the package under a new id.
- The launch routes (`.../blocks/{block_id}/html-widget`, preview under `lms_authoring`) return a signed `entry_url`
  `/v1/lms/html-widgets/{token}/index.html`, valid one hour, keyed by its own HMAC label (an H5P token is rejected).
- Files are served with `Content-Security-Policy: sandbox allow-scripts allow-popups; default-src 'none'; connect-src
  'none'; form-action 'none'; frame-ancestors <LMS origin>; ...`, `X-Content-Type-Options: nosniff`, no cookies
  (nginx strips `Cookie`, `Authorization`, `Set-Cookie`). The iframe is `sandbox="allow-scripts allow-popups"`, opaque
  origin: no parent DOM, cookies, storage, network, forms or top navigation.
- The page accepts a message only when `event.origin === "null"` and `event.source` is this widget's frame.

## postMessage protocol

- `{type: "ihsp-widget-size", height}`: the frame height, clamped to 200..2000 px.
- `{type: "ihsp-widget-result", score_pct: 0..100, passed: boolean}`: graded blocks post it to
  `POST /v1/lms/courses/{course_id}/steps/{step_id}/blocks/{block_id}/result`; the best score is kept.

## SDK, tokens, i18n, accessibility

- `IHSP.reportScore(pct, passed?)`, `IHSP.resize()` (automatic via ResizeObserver), `IHSP.lang` (`uz|ru|en`),
  `IHSP.theme` (`light|dark`), `IHSP.t({uz, ru, en})`. The player passes `#lang=..&theme=..` in the URL hash.
- Style with the CSS variables of `ihsp-widget.css` (`--background`, `--foreground`, `--primary`, `--muted-foreground`,
  `--border`, `--radius`, `--font-sans`) and the `.ihsp-button`, `.ihsp-input`, `.ihsp-card` classes.
- Provide every text in uz, ru (formal) and en; uz uses ʼ (U+02BC). Use ПК/ИК, never "Рубежный контроль".
- Real buttons and labels, 44 px touch targets, visible focus, `prefers-reduced-motion`, works at 375 px width.

## Minimal example

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <link rel="stylesheet" href="ihsp-widget.css" />
    <script src="ihsp-widget.js"></script>
  </head>
  <body>
    <h1 id="q"></h1>
    <button class="ihsp-button" onclick="IHSP.reportScore(100)">4</button>
    <button class="ihsp-button" data-variant="outline" onclick="IHSP.reportScore(0)">5</button>
    <script>
      document.getElementById("q").textContent = IHSP.t({ uz: "2 + 2 = ?", ru: "2 + 2 = ?", en: "2 + 2 = ?" })
    </script>
  </body>
</html>
```

Zip it with `cd widget && zip -r ../widget.zip .` (index.html at the root), then upload it in the step editor.
Tests: `tests/lms/unit/test_html_widget_package.py`, `tests/lms/learning/http/test_html_widget_file_route.py`,
`tests/lms/authoring/integration/test_html_widget_upload.py`, web `e2e/lms-html-widget-security.spec.ts`.
