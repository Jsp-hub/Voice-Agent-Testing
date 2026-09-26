"""Print the authorized outbound-call request without making a telephone call.-----Dry Run(No actual Call)"""

from __future__ import annotations

import json
from datetime import datetime

from src.telephony.outbound_call import (
    AUTHORIZED_TEST_NUMBER,
    build_authorized_call_request,
    describe_dry_run,
)


def main() -> None:
    room_name = f"assessment-call-{datetime.now():%Y%m%d-%H%M%S}"
    request = build_authorized_call_request(
        room_name=room_name,
        destination=AUTHORIZED_TEST_NUMBER,
    )
    print(json.dumps(describe_dry_run(request), indent=2))


if __name__ == "__main__":
    main()
