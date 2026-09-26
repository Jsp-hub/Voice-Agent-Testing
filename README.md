# Voice Bot Assessment

An automated, pipeline-mode LiveKit patient simulator for testing the authorized assessment line.

The runtime keeps its speech-to-text, text-LLM, and text-to-speech adapters as separate components. The agent layer only orchestrates those components and the LiveKit session.

This project is being built incrementally.
# Voice-BOT Assessment Simulator

## First LLM rehearsal

The first milestone tests only the patient-simulator LLM. It does not connect to
LiveKit Cloud, generate audio, or make a phone call.

1. Copy `.env.example` to `.env` and add your Google AI Studio API key.
2. Run the simulator from the project root:

   ```powershell
   python -m src.agent.text_simulator
   ```

Enter a hypothetical support-agent utterance when prompted. The program prints
the simulated patient's next reply. Type `/quit` to stop.

### Rehearsal safeguards

- Gemini replies target 22 words and have a 48-token ceiling, keeping typical
  turns brief while leaving enough room to finish a complete sentence.
- A failed Gemini request is retried up to three times. Technical error text is
  never presented as patient dialogue.
- If retries fail, the simulator uses one fixed polite goodbye and ends.
- The scenario includes a five-minute and 20-turn ceiling. The later phone agent
  will also use a three-consecutive-dead-end rule to end an unproductive call.

## Voice-only LiveKit rehearsal

This milestone uses a separate pipeline with Deepgram STT, Gemini LLM, and xAI
TTS. The browser rehearsal itself does not place a phone call.

1. Add `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, and
   `DEEPGRAM_API_KEY` to your local `.env` file.
2. Install the complete reproducible dependency set:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Start a private audio rehearsal with the LiveKit CLI:

   ```powershell
   lk agent console src/agent/voice_agent.py
   ```

The voice agent opens as the patient, streams each Gemini response to xAI TTS,
and closes the private room after five minutes or 20 final user turns. Stop it
with `Ctrl+C` at any time.

## Outbound assessment call

Add `LIVEKIT_OUTBOUND_TRUNK_ID` and `TELNYX_CALLER_NUMBER` to `.env`.

Dry-run only (no call):

```powershell
python -m scripts.prepare_outbound_call
```

To place one real, authorized assessment call—while the voice worker is running:

```powershell
python -m scripts.dial_assessment --dial --confirm-authorized-test-call
```

The dial command is hard-locked to `+1-805-439-8008`.
