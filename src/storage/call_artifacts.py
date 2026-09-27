"""Small, local call-artifact store for assessment evidence."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_FOLDER_PATTERN = re.compile(r"^Transcript_(\d+)$")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class CallArtifact:
    """Owns the human-readable files for one test call."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.transcript_path = directory / "transcript.txt"
        self.recording_path = directory / "recording.mp3"
        self.metadata_path = directory / "metadata.json"

    @classmethod
    def create(cls, artifacts_root: Path, metadata: dict[str, Any]) -> "CallArtifact":
        artifacts_root.mkdir(parents=True, exist_ok=True)
        highest = 0
        for child in artifacts_root.iterdir():
            match = _FOLDER_PATTERN.match(child.name)
            if child.is_dir() and match:
                highest = max(highest, int(match.group(1)))

        for number in range(highest + 1, highest + 10_000):
            directory = artifacts_root / f"Transcript_{number:03d}"
            try:
                directory.mkdir()
            except FileExistsError:
                continue

            artifact = cls(directory)
            artifact.transcript_path.write_text(
                f"Assessment call transcript\nStarted: {now_iso()}\n\n",
                encoding="utf-8",
            )
            artifact.write_metadata(
                {
                    "artifact_id": directory.name,
                    "started_at": now_iso(),
                    "status": "starting",
                    **metadata,
                }
            )
            return artifact

        raise RuntimeError("Could not allocate a new transcript artifact directory.")

    @classmethod
    def open(cls, directory: str | Path) -> "CallArtifact":
        artifact = cls(Path(directory))
        if not artifact.metadata_path.exists():
            raise FileNotFoundError(f"Artifact metadata is missing: {artifact.metadata_path}")
        return artifact

    def read_metadata(self) -> dict[str, Any]:
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        temporary_path = self.metadata_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        temporary_path.replace(self.metadata_path)

    def update_metadata(self, **updates: Any) -> None:
        metadata = self.read_metadata()
        metadata.update(updates)
        self.write_metadata(metadata)

    def append_transcript(self, *, speaker: str, text: str, interrupted: bool = False) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        suffix = " [interrupted]" if interrupted else ""
        with self.transcript_path.open("a", encoding="utf-8") as transcript:
            transcript.write(f"[{now_iso()}] {speaker}{suffix}:\n{cleaned}\n\n")


class DebugLogCapture:
    """Attach raw runtime logging to one artifact only when explicitly enabled."""

    def __init__(self, artifact: CallArtifact, enabled: bool) -> None:
        self._handler: logging.Handler | None = None
        if not enabled:
            return

        handler = logging.FileHandler(artifact.directory / "debug.log", encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logging.getLogger().addHandler(handler)
        self._handler = handler

    def close(self) -> None:
        if self._handler is None:
            return
        logging.getLogger().removeHandler(self._handler)
        self._handler.close()
        self._handler = None
