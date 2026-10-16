# Manga Arabic Translator

Arabic RTL web app prototype for uploading one manga page, detecting English text with Tesseract OCR, optionally translating regions using the OpenAI API, editing Arabic text, inpainting detected regions and downloading a PNG.

## Deploy
Render can build this repository using the root Dockerfile or render.yaml. Set `OPENAI_API_KEY` in the service environment to enable billed AI translation. Never put API keys in browser code or commit them to GitHub.

## Current limits
This is an MVP for one image at a time. It is not yet a full chapter/PDF/ZIP platform and has no user accounts, durable cloud storage, multi-user isolation or background queue. The free host may sleep and local image files may not persist across redeploys. OCR and background reconstruction can be inaccurate, so manually review the result. Do not upload sensitive/private content before production security and storage improvements.
