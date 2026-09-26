"""Voice-only LiveKit rehearsal agent.

This module intentionally contains no SIP trunk or phone-number configuration.
It can be tested only in a LiveKit room until outbound telephony is added later.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
    inference,
)
from livekit.plugins import deepgram, google, silero

from src.scenarios.prompting import build_instructions, load_scenario


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)
server = AgentServer()


class PatientSimulator(Agent):
    """A patient role whose behavior is constrained by one scenario card."""

    def __init__(self) -> None:
        super().__init__(instructions=build_instructions(load_scenario()))


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value or value.startswith("replace_with_"):
        raise RuntimeError(f"{name} is missing. Add it to .env before starting the agent.")
    return value


async def graceful_finish(
    ctx: JobContext,
    session: AgentSession,
    message: str,
) -> None:
    """Speak a fixed goodbye, then close the private rehearsal room."""
    try:
        await session.say(message, allow_interruptions=False)
    except Exception:
        logger.exception("Unable to play the final voice message")
    await ctx.delete_room()


@server.rtc_session(agent_name="patient-simulator-rehearsal")
async def entrypoint(ctx: JobContext) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    google_api_key = required_environment("GOOGLE_API_KEY")
    required_environment("DEEPGRAM_API_KEY")
    required_environment("LIVEKIT_URL")
    required_environment("LIVEKIT_API_KEY")
    required_environment("LIVEKIT_API_SECRET")

    scenario = load_scenario()
    controls = scenario["conversation_controls"]
    session = AgentSession(
        stt=deepgram.STTv2(
            model="flux-general-en",
            eager_eot_threshold=0.4,
        ),
        llm=google.LLM(
            model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
            api_key=google_api_key,
            temperature=0.7,
            max_output_tokens=controls["llm_max_output_tokens"],
        ),
        tts=inference.TTS(
            model=os.getenv("XAI_TTS_MODEL", "xai/tts-1"),
            voice=os.getenv("XAI_TTS_VOICE", "ara"),
            language="en",
        ),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            endpointing={
                "mode": "fixed",
                "min_delay": 0.4,
                "max_delay": 2.0,
            },
            interruption={
                "enabled": True,
                "mode": "adaptive",
                "min_duration": 0.35,
                "min_words": 1,
                "false_interruption_timeout": 1.0,
                "resume_false_interruption": False,
                "discard_audio_if_uninterruptible": True,
                "backchannel_boundary": (0.2, 0.2),
            },
            preemptive_generation={
                "enabled": True,
                "preemptive_tts": False,
                "max_retries": 3,
            },
        ),
    )

    state = {"turns": 0, "ending": False}

    async def end_rehearsal(message: str) -> None:
        if state["ending"]:
            return
        state["ending"] = True
        await graceful_finish(ctx, session, message)

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event) -> None:
        if not event.is_final or state["ending"]:
            return

        state["turns"] += 1
        if state["turns"] >= controls["maximum_turns"]:
            asyncio.create_task(
                end_rehearsal("Thank you for your help. I need to go now. Goodbye.")
            )

    await session.start(agent=PatientSimulator(), room=ctx.room)
    await ctx.connect()

    timeout_task = asyncio.create_task(
        asyncio.sleep(controls["maximum_call_seconds"])
    )
    try:
        await session.say(
            "Hi, I have had knee pain after running and wanted to ask about an appointment.",
            allow_interruptions=True,
        )
        await timeout_task
        await end_rehearsal("I’m sorry, I need to go now. Goodbye.")
    finally:
        timeout_task.cancel()


if __name__ == "__main__":
    cli.run_app(server)
