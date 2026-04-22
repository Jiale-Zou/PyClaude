from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSkill(ABC):
    name: str

    @abstractmethod
    def can_handle(self, user_input: str) -> bool: ...

    @abstractmethod
    def run(self, user_input: str) -> str: ...
