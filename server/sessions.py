"""Session store: persisted GameState, capability tokens, and one-turn-at-a-time locks.

Single process only: locks live in memory. State and token hashes persist under ``states/``
so a server restart (or a browser refresh) resumes the same session.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.cartridge import Cartridge, load_cartridge
from core.state import GameState, load_state, new_game, save_state

ROOT = Path(__file__).resolve().parents[1]
STATES_DIR = Path(os.environ.get("POLYTALE_STATES_DIR", ROOT / "states"))


class SessionNotFound(LookupError):
    pass


class BadToken(PermissionError):
    pass


@lru_cache(maxsize=16)
def cartridge(cartridge_id: str) -> Cartridge:
    return load_cartridge(cartridge_id)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class SessionStore:
    root: Path = STATES_DIR
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def _auth_path(self, session_id: str) -> Path:
        return self.root / "auth" / f"{session_id}.json"

    def create(self, cartridge_id: str) -> tuple[GameState, str]:
        cart = cartridge(cartridge_id)
        session_id = secrets.token_urlsafe(12)
        token = secrets.token_urlsafe(24)
        state = new_game(cart, session_id)
        save_state(state, self.root)
        path = self._auth_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"token_sha256": _digest(token)}))
        return state, token

    def authorize(self, session_id: str, token: str | None) -> GameState:
        """Load a session after checking its token. Unknown → SessionNotFound; bad → BadToken."""
        path = self._auth_path(session_id)
        state = load_state(session_id, self.root) if path.is_file() else None
        if state is None:
            raise SessionNotFound(session_id)
        expected = json.loads(path.read_text())["token_sha256"]
        if not token or not hmac.compare_digest(expected, _digest(token)):
            raise BadToken(session_id)
        return state

    def save(self, state: GameState) -> None:
        save_state(state, self.root)

    def reset(self, state: GameState) -> GameState:
        fresh = new_game(cartridge(state.cartridge_id), state.session_id)
        save_state(fresh, self.root)
        return fresh

    def lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())
