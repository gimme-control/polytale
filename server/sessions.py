"""Journey store: persisted state, capability tokens, one-turn-at-a-time locks, content cache.

Single process only: locks live in memory. Journeys and token hashes persist under ``states/``
so a restart or a browser refresh resumes the same journey.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from core.content import CONTENT_ROOT, Content, load_content
from core.state import Journey, load_journey, new_journey, save_journey

ROOT = Path(__file__).resolve().parents[1]
STATES_DIR = Path(os.environ.get("POLYTALE_STATES_DIR", ROOT / "states"))

_cached: tuple[tuple[float, ...], Content] | None = None


def content() -> Content:
    """Validated content, reloaded when any content JSON changes on disk."""
    global _cached
    signature = tuple(p.stat().st_mtime for p in sorted(CONTENT_ROOT.rglob("*.json")))
    if _cached is None or _cached[0] != signature:
        _cached = (signature, load_content())
    return _cached[1]


class JourneyNotFound(LookupError):
    pass


class BadToken(PermissionError):
    pass


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class JourneyStore:
    root: Path = STATES_DIR
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _auth_path(self, journey_id: str) -> Path:
        return self.root / "auth" / f"{journey_id}.json"

    def create(self, *, language: str) -> tuple[Journey, str]:
        journey_id = secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(24)
        journey = new_journey(content(), journey_id, language=language)
        save_journey(journey, self.root)
        path = self._auth_path(journey_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"token_sha256": _digest(token)}))
        return journey, token

    def authorize(self, journey_id: str, token: str | None) -> Journey:
        """Load a journey after checking its token. Unknown → JourneyNotFound; bad → BadToken."""
        path = self._auth_path(journey_id)
        journey = load_journey(journey_id, self.root) if path.is_file() else None
        if journey is None:
            raise JourneyNotFound(journey_id)
        expected = json.loads(path.read_text())["token_sha256"]
        if not token or not hmac.compare_digest(expected, _digest(token)):
            raise BadToken(journey_id)
        return journey

    def save(self, journey: Journey) -> None:
        save_journey(journey, self.root)

    def reset(self, journey: Journey) -> Journey:
        fresh = new_journey(content(), journey.journey_id, language=journey.language)
        save_journey(fresh, self.root)
        return fresh

    def lock(self, journey_id: str) -> asyncio.Lock:
        return self._locks.setdefault(journey_id, asyncio.Lock())
