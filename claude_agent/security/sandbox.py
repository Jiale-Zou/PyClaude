from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Sandbox:
    def run(self) -> None:
        return
