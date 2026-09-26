"""Safe, dry-run preparation for assessment outbound calls.

This module deliberately cannot dial by default. Its job for this checkpoint is
to validate configuration and show the exact LiveKit SIP request that will be
used after a separately approved real-call step.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from dotenv import load_dotenv
load_dotenv()

# Challenge authorization: outbound calls may only ever be directed here.
AUTHORIZED_TEST_NUMBER = "+18054398008"


@dataclass(frozen=True)
class OutboundCallRequest:
    room_name: str
    destination: str
    trunk_id: str
    caller_number: str
    participant_identity: str = "assessment-support-agent"
    participant_name: str = "Assessment Support Agent"
    wait_until_answered: bool = True


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("replace-with"):
        raise ValueError(f"{name} must be set in .env before preparing a call.")
    return value


def build_authorized_call_request(*, room_name: str, destination: str) -> OutboundCallRequest:
    """Build a request only if its destination is the challenge test number."""
    if destination != AUTHORIZED_TEST_NUMBER:
        raise ValueError(
            "Outbound calls are restricted to the authorized assessment test number."
        )

    return OutboundCallRequest(
        room_name=room_name,
        destination=destination,
        trunk_id=_required("LIVEKIT_OUTBOUND_TRUNK_ID"),
        caller_number=_required("TELNYX_CALLER_NUMBER"),
    )


def describe_dry_run(request: OutboundCallRequest) -> dict[str, object]:
    """Return reviewable data without performing a network action."""
    return {
        "mode": "DRY RUN — no call will be placed",
        "livekit_sip_request": asdict(request),
        "next_step": "Wire this to LiveKit's SIP API only behind a separately reviewed --dial flag.",
    }


def require_authorized_dial_confirmation(*, dial: bool, confirmation: bool) -> None:
    """Refuse real telephony unless the caller explicitly acknowledges it."""
    if not dial:
        raise ValueError("Refusing to dial: pass --dial to request a real call.")
    if not confirmation:
        raise ValueError(
            "Refusing to dial: pass --confirm-authorized-test-call to acknowledge "
            "that this places a real call to the authorized assessment number."
        )
