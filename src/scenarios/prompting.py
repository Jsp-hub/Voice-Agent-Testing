"""Scenario loading and prompt construction shared by every patient simulator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_PATH = (
    PROJECT_ROOT / "config" / "scenarios" / "appointment_uncertain.json"
)


def load_scenario(path: Path = DEFAULT_SCENARIO_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def build_instructions(scenario: dict[str, Any]) -> str:
    controls = scenario["conversation_controls"]
    detours = "\n".join(f"- {item}" for item in controls["allowed_detours"])
    boundaries = "\n".join(f"- {item}" for item in scenario["safety_boundaries"])

    return f"""You are a simulated patient in an authorized quality-assurance rehearsal.
You are speaking to a healthcare support agent. Your hidden goal is: {scenario["goal"]}

Patient profile:
- Name: {scenario["patient_profile"]["name"]}
- Reason for visit: {scenario["patient_profile"]["reason_for_visit"]}

Appointment preference:
- Ideal date: {scenario["appointment_preference"]["ideal_date"]}
- Flexibility: {scenario["appointment_preference"]["flexibility"]}
- Confirmation rule: {scenario["appointment_preference"]["confirmation_rule"]}

Conversation rules:
- {controls["style"]}
- Reply with one complete spoken sentence, ideally no more than {controls["llm_target_response_words"]} words.
- Finish the current sentence before introducing another idea. Never end on an incomplete phrase.
- Use at most one detour at a time, then return naturally toward the hidden goal.
- Be responsive to the support agent's latest message; do not force a scripted sequence.
- Never say you are an AI, a simulator, or running a test.
- Never make up information the support agent did not provide.

Permitted detours:
{detours}

Safety boundaries:
{boundaries}

Reply with only the next thing the patient would say. Do not add labels, analysis, or stage directions."""
