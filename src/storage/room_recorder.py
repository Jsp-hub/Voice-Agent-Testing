"""A local, read-only LiveKit participant that saves a stereo MP3 call recording."""

from __future__ import annotations

import asyncio
import os
import time
from array import array
from pathlib import Path

import av
from livekit import api, rtc


SAMPLE_RATE = 24_000
SUPPORT_AGENT_IDENTITY = "assessment-support-agent"


class RoomRecorder:
    """Capture SIP audio on the left channel and patient-bot audio on the right."""

    def __init__(self, *, room_name: str, output_path: Path) -> None:
        self._room_name = room_name
        self._output_path = output_path
        self._room = rtc.Room()
        self._started_at = time.monotonic()
        self._support = array("h")
        self._patient = array("h")
        self._tasks: list[asyncio.Task[None]] = []
        self._finished = asyncio.Event()

    async def start(self) -> None:
        token = (
            api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(f"artifact-recorder-{self._room_name}")
            .with_name("Artifact Recorder")
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=self._room_name,
                    can_publish=False,
                    can_subscribe=True,
                )
            )
            .to_jwt()
        )

        @self._room.on("track_subscribed")
        def on_track_subscribed(track, _publication, participant) -> None:
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            if participant.identity.startswith("artifact-recorder-"):
                return
            channel = "support" if participant.identity == SUPPORT_AGENT_IDENTITY else "patient"
            self._tasks.append(asyncio.create_task(self._capture_track(track, channel)))

        @self._room.on("participant_disconnected")
        def on_participant_disconnected(participant) -> None:
            if participant.identity == SUPPORT_AGENT_IDENTITY:
                self._finished.set()

        @self._room.on("disconnected")
        def on_disconnected(*_args) -> None:
            self._finished.set()

        await self._room.connect(os.environ["LIVEKIT_URL"], token)

    async def wait_until_finished(self) -> None:
        await self._finished.wait()

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._room.disconnect()
        self._encode_mp3()

    async def _capture_track(self, track: rtc.Track, channel: str) -> None:
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        async for event in stream:
            frame = event.frame
            samples = array("h")
            samples.frombytes(bytes(frame.data))
            self._append(channel, samples, time.monotonic())

    def _append(self, channel: str, samples: array, received_at: float) -> None:
        target = self._support if channel == "support" else self._patient
        target_offset = int((received_at - self._started_at) * SAMPLE_RATE)
        if len(target) < target_offset:
            target.extend(array("h", [0]) * (target_offset - len(target)))
        target.extend(samples)

    def _encode_mp3(self) -> None:
        total_samples = max(len(self._support), len(self._patient), SAMPLE_RATE)
        self._support.extend(array("h", [0]) * (total_samples - len(self._support)))
        self._patient.extend(array("h", [0]) * (total_samples - len(self._patient)))

        container = av.open(str(self._output_path), mode="w", format="mp3")
        stream = container.add_stream("mp3", rate=SAMPLE_RATE)
        stream.layout = "stereo"
        stream.bit_rate = 64_000
        chunk_size = 1_152

        try:
            for offset in range(0, total_samples, chunk_size):
                count = min(chunk_size, total_samples - offset)
                interleaved = array("h")
                for index in range(offset, offset + count):
                    interleaved.append(self._support[index])
                    interleaved.append(self._patient[index])

                frame = av.AudioFrame(format="s16", layout="stereo", samples=count)
                frame.sample_rate = SAMPLE_RATE
                frame.planes[0].update(interleaved.tobytes())
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        finally:
            container.close()
