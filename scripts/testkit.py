"""Minimal PASS/FAIL harness shared by the standalone test scripts (no pytest)."""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class Checker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = 0
        self.failed: list[str] = []

    def check(self, label: str, condition: bool, detail: Any = "") -> bool:
        if condition:
            self.passed += 1
            print(f"PASS {label}")
        else:
            self.failed.append(label)
            print(f"FAIL {label}" + (f" :: {detail}" if detail != "" else ""))
        return condition

    def run(self, label: str, fn: Callable[[], None]) -> None:
        """Run a test function; an exception counts as a failure."""
        try:
            fn()
        except Exception:
            self.failed.append(label)
            print(f"FAIL {label} raised:\n{traceback.format_exc()}")

    def finish(self) -> None:
        total = self.passed + len(self.failed)
        status = "OK" if not self.failed else "FAILED"
        print(f"\n{self.name}: {self.passed}/{total} passed — {status}")
        if self.failed:
            print("failures: " + ", ".join(self.failed))
            sys.exit(1)


# ---------------------------------------------------------------- scripted Gemini client


def call(name: str, **args: Any) -> Any:
    from google.genai import types

    return types.Part(function_call=types.FunctionCall(name=name, args=args, id=f"id-{name}"))


def reply(*parts: Any) -> Any:
    from google.genai import types

    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


def text_reply(text: str) -> Any:
    from google.genai import types

    return reply(types.Part(text=text))


class FakeModels:
    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: list[Any], config: Any) -> Any:
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        if not self.script:
            raise AssertionError("fake client script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    """Stands in for ``genai.Client``: replays scripted responses (or raises scripted errors)."""

    def __init__(self, script: list[Any]) -> None:
        self.models = FakeModels(script)


def lexicon_line(language: Any, item_ids: list[str], highlight: list[str] | None = None) -> dict:
    """A valid ``say`` line made of the given lexicon items (works for any language file)."""
    return {
        "segments": [
            {"t": language.items[i].text, "r": language.items[i].roman} for i in item_ids
        ],
        "item_ids": list(item_ids),
        "highlight_object_ids": list(highlight or []),
    }


def say(*lines: dict, hint: str = "Wants to know what you would like", mood: str = "neutral",
        narration: str = "You wait. The night does not.") -> Any:
    return call("say", lines=list(lines), intent_hint=hint, mood=mood, narration=narration)
