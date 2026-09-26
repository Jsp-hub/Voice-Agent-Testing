"""Place one explicitly authorized assessment call through LiveKit SIP.

This command is intentionally guarded twice. It rejects all destinations except
the challenge's authorized test number and requires two explicit command flags.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from livekit import api

from src.telephony.outbound_call import (
    AUTHORIZED_TEST_NUMBER,
    build_authorized_call_request,
    require_authorized_dial_confirmation,
)

AGENT_NAME = "patient-simulator-rehearsal"


async def dial() -> None:
    room_name = f"assessment-call-{datetime.now():%Y%m%d-%H%M%S}"
    request = build_authorized_call_request(
        room_name=room_name,
        destination=AUTHORIZED_TEST_NUMBER,
    )
    livekit_api = api.LiveKitAPI()

    try:
        dispatch = await livekit_api.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata='{"call_type":"authorized_assessment"}',
            )
        )
        print(f"Agent dispatched: {dispatch.id}")
        print(f"Dialing the authorized assessment number in room: {room_name}")

        participant = await livekit_api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=request.room_name,
                sip_trunk_id=request.trunk_id,
                sip_call_to=request.destination,
                participant_identity=request.participant_identity,
                participant_name=request.participant_name,
                wait_until_answered=request.wait_until_answered,
            )
        )
        print(f"Call answered; SIP participant joined: {participant.participant_id}")
    finally:
        await livekit_api.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dial", action="store_true", help="request a real outbound call")
    parser.add_argument(
        "--confirm-authorized-test-call",
        action="store_true",
        help="acknowledge that this places a real call to the assessment number",
    )
    args = parser.parse_args()

    load_dotenv()
    require_authorized_dial_confirmation(
        dial=args.dial,
        confirmation=args.confirm_authorized_test_call,
    )
    asyncio.run(dial())


if __name__ == "__main__":
    main()
