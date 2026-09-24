# Implementation checkpoints

## Chosen services

- Telephony: Telnyx SIP trunk for outbound calls only.
- STT: Deepgram API.
- LLM: Gemini text model through the project's Google API key.
- TTS: Rime Mist v3 through LiveKit Inference.

## Recording checkpoint

When implementing call artifacts, build a Python recorder that captures the two LiveKit audio tracks locally as a dual-track recording. Do not enable Telnyx provider-side recording unless it is needed as a temporary fallback.
