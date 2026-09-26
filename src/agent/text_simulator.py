"""Run a text-only rehearsal of the patient-simulator LLM.

This is deliberately separate from audio and SIP. It validates scenario steering,
conversation memory, and the Gemini integration before a real phone call is involved.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import ChatContext
from livekit.plugins import google

from src.scenarios.prompting import build_instructions, load_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


async def generate_patient_reply(
    model: google.LLM,
    chat_ctx: ChatContext,
    *,
    maximum_attempts: int,
    base_delay_seconds: float,
) -> str | None:
    """Return a reply after bounded retries, never exposing provider errors as speech."""
    for attempt in range(1, maximum_attempts + 1):
        try:
            response = await model.chat(chat_ctx=chat_ctx).collect()
            patient_line = response.text.strip()
            if not patient_line:
                raise RuntimeError("Gemini returned an empty reply")
            return patient_line
        except Exception:
            logger.warning(
                "Gemini generation failed on attempt %s of %s.",
                attempt,
                maximum_attempts,
                exc_info=True,
            )
            if attempt == maximum_attempts:
                return None

            delay = base_delay_seconds * attempt
            print(f"Patient model unavailable; retrying in {delay:.0f} second(s)...")
            await asyncio.sleep(delay)

    return None


async def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("GOOGLE_API_KEY")
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is missing. Copy .env.example to .env and add your key."
        )

    scenario = load_scenario()
    controls = scenario["conversation_controls"]
    chat_ctx = ChatContext()
    chat_ctx.add_message(role="system", content=build_instructions(scenario))
    model = google.LLM(
        model=model_name,
        api_key=api_key,
        temperature=0.7,
        max_output_tokens=controls["llm_max_output_tokens"],
    )

    print(f"Scenario: {scenario['title']}")
    print("Enter a support-agent line. Type /quit to stop.\n")

    turn = 0
    started_at = time.monotonic()
    maximum_turns = controls["maximum_turns"]
    maximum_seconds = controls["maximum_call_seconds"]
    retry_policy = controls["retry_policy"]
    try:
        while True:
            if time.monotonic() - started_at >= maximum_seconds:
                print("Scenario time limit reached. Ending rehearsal.")
                break

            support_line = input("Support agent > ").strip()
            if support_line.lower() in {"/quit", "/exit"}:
                break
            if not support_line:
                continue

            turn += 1
            chat_ctx.add_message(
                role="user",
                content=(
                    f"Support agent: {support_line}\n\n"
                    f"Internal turn state: {turn} of {maximum_turns}. "
                    "Do not mention this state to the support agent."
                ),
            )
            patient_line = await generate_patient_reply(
                model,
                chat_ctx,
                maximum_attempts=retry_policy["maximum_attempts"],
                base_delay_seconds=retry_policy["base_delay_seconds"],
            )
            if patient_line is None:
                print(
                    "Patient       > I’m sorry, I’m having trouble with the line. "
                    "I’ll try again later. Goodbye."
                )
                print("Model retries exhausted. Ending rehearsal.")
                break

            chat_ctx.add_message(role="assistant", content=patient_line)

            print(f"Patient       > {patient_line}\n")
            if turn >= maximum_turns:
                print("Scenario turn limit reached. Ending rehearsal.")
                break
    finally:
        await model.aclose()


if __name__ == "__main__":
    asyncio.run(main())
