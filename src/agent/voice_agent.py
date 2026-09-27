"""Voice-only LiveKit rehearsal agent.

This module intentionally contains no SIP trunk or phone-number configuration.
It can be tested only in a LiveKit room until outbound telephony is added later.
"""

from __future__ import annotations

import asyncio
import json
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
    room_io,
)
from livekit.plugins import deepgram, google, silero

from src.scenarios.prompting import build_instructions, load_scenario
from src.storage.call_artifacts import CallArtifact, DebugLogCapture, now_iso


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

    try:
        dispatch_metadata = json.loads(ctx.job.metadata or "{}")
    except json.JSONDecodeError:
        dispatch_metadata = {}

    artifact: CallArtifact | None = None
    debug_capture: DebugLogCapture | None = None
    artifact_directory = dispatch_metadata.get("artifact_directory")
    if artifact_directory:
        artifact = CallArtifact.open(artifact_directory)
        artifact.update_metadata(
            room_name=ctx.room.name,
            agent_name="patient-simulator-rehearsal",
            status="in_progress",
        )
        debug_capture = DebugLogCapture(
            artifact,
            enabled=os.getenv("SAVE_DEBUG_LOGS", "false").strip().lower() == "true",
        )

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
            voice="rex",
            language="en",
            extra_kwargs={"speed": 1.5},
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

    state = {"turns": 0, "ending": False, "last_user_turn_at": None}
    finished = asyncio.Event()
    first_support_turn = asyncio.Event()

    async def end_rehearsal(message: str) -> None:
        if state["ending"]:
            return
        state["ending"] = True
        await graceful_finish(ctx, session, message)
        finished.set()

    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event) -> None:
        if not event.is_final or state["ending"]:
            return

        state["turns"] += 1
        state["last_user_turn_at"] = asyncio.get_running_loop().time()
        first_support_turn.set()
        if state["turns"] >= controls["maximum_turns"]:
            asyncio.create_task(
                end_rehearsal("Thank you for your help. I need to go now. Goodbye.")
            )

    @session.on("conversation_item_added")
    def on_conversation_item_added(event) -> None:
        if artifact is None:
            return
        item = event.item
        role = getattr(item, "role", None)
        text = getattr(item, "raw_text_content", "")
        if role not in {"user", "assistant"} or not text:
            return

        artifact.append_transcript(
            speaker="Support agent" if role == "user" else "Patient bot",
            text=text,
            interrupted=bool(getattr(item, "interrupted", False)),
        )
        if role == "assistant" and state["last_user_turn_at"] is not None:
            latency_ms = round(
                (asyncio.get_running_loop().time() - state["last_user_turn_at"]) * 1000
            )
            metadata = artifact.read_metadata()
            turn_latencies = metadata.get("assistant_text_committed_latency_ms", [])
            turn_latencies.append(latency_ms)
            artifact.update_metadata(assistant_text_committed_latency_ms=turn_latencies)

    @session.on("close")
    def on_session_close(_event) -> None:
        finished.set()

    # Explicit SIP participant selection needs a connected local participant.
    # The older browser-only rehearsal happened to work with the reverse order.
    await ctx.connect()

    if dispatch_metadata.get("call_type") == "authorized_assessment":
        await session.start(
            agent=PatientSimulator(),
            room=ctx.room,
            room_options=room_io.RoomOptions(participant_identity="assessment-support-agent"),
        )
    else:
        await session.start(agent=PatientSimulator(), room=ctx.room)

    timeout_task = asyncio.create_task(
        asyncio.sleep(controls["maximum_call_seconds"])
    )
    try:
        try:
            await asyncio.wait_for(first_support_turn.wait(), timeout=8)
        except asyncio.TimeoutError:
            await session.say(
                "Hello, I’m calling about recurring knee pain and wanted to ask about an appointment.",
                allow_interruptions=True,
            )
        finished_task = asyncio.create_task(finished.wait())
        done, _ = await asyncio.wait(
            {timeout_task, finished_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if timeout_task in done and not state["ending"]:
            await end_rehearsal("I’m sorry, I need to go now. Goodbye.")
        finished_task.cancel()
    finally:
        timeout_task.cancel()
        if artifact is not None:
            artifact.update_metadata(
                ended_at=now_iso(),
                status="completed",
                final_user_turns=state["turns"],
            )
        if debug_capture is not None:
            debug_capture.close()


if __name__ == "__main__":
    cli.run_app(server)
