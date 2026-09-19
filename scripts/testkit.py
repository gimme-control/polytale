"""Minimal PASS/FAIL harness shared by the standalone test scripts (no pytest)."""

from __future__ import annotations

import copy
import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARTRIDGE_ID = "broken-airship-ja"


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


def raw_cartridge() -> dict[str, Any]:
    """A fresh deep copy of the real cartridge JSON."""
    path = ROOT / "cartridges" / CARTRIDGE_ID / "cartridge.json"
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))


def plain_cartridge_data() -> dict[str, Any]:
    """The real cartridge stripped of ``language_learning`` (plain story mode)."""
    data = raw_cartridge()
    del data["language_learning"]
    for obj in data["objects"]:
        obj["concept_id"] = None
    for line in data["opening"]["spoken_lines"]:
        line["concept_ids"] = []
    return data
