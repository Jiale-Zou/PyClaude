from __future__ import annotations

import doctest
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class PathDecisionType(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PathDecision:
    decision: PathDecisionType
    normalized: str
    reason: str


@dataclass(slots=True)
class PathValidator:
    allowed_roots: tuple[Path, ...] = (Path.cwd(),) # 默认只允许当前工作目录
    blocked_extensions: tuple[str, ...] = (".exe", ".dll", ".bin", ".so") # 阻止的文件扩展名
    blocked_dir_markers: tuple[tuple[str, ...], ...] = ( # 阻止的目录特征
        (".git", "hooks"),
        ("etc",),
        ("root",),
        (".sbin",),
    )

    def _normalize_str(self, path: str | Path) -> str:
        '''路径标准化'''
        p = Path(path) if not isinstance(path, Path) else path
        try:
            return str(p.expanduser()) # 展开 ~ 为 /home/username
        except Exception:
            return str(p)

    def _contains_parent_segments(self, raw: str | Path) -> bool:
        '''检测..'''
        p = Path(raw) if not isinstance(raw, Path) else raw
        return any(part == ".." for part in p.parts)

    def _is_within_any_root(self, resolved: Path, roots: Iterable[Path]) -> bool:
        '''检查是否在root内'''
        for root in roots:
            try:
                resolved.relative_to(root.resolve())
                return True
            except Exception:
                continue
        return False

    def _is_sensitive(self, resolved: Path) -> bool:
        '''敏感路径检测'''
        suffix = resolved.suffix.lower()
        if suffix and suffix in {ext.lower() for ext in self.blocked_extensions}:
            return True

        parts = [p.lower() for p in resolved.parts]
        for marker in self.blocked_dir_markers:
            marker_l = [m.lower() for m in marker]
            if len(marker_l) == 1:
                if marker_l[0] in parts:
                    return True
                continue
            for i in range(0, len(parts) - len(marker_l) + 1):
                if parts[i : i + len(marker_l)] == marker_l:
                    return True
        return False

    def classify(self, path: str | Path) -> PathDecision:
        normalized = self._normalize_str(path).strip()
        if not normalized:
            return PathDecision(
                decision=PathDecisionType.CONFIRM,
                normalized="",
                reason="Empty path requires confirmation.",
            )

        raw_path = Path(normalized)
        if self._contains_parent_segments(raw_path):
            return PathDecision(
                decision=PathDecisionType.CONFIRM,
                normalized=normalized,
                reason='Path contains ".." segments; requires confirmation.',
            )

        try:
            resolved = raw_path.expanduser().resolve(strict=False)
        except Exception:
            return PathDecision(
                decision=PathDecisionType.CONFIRM,
                normalized=normalized,
                reason="Path cannot be resolved safely; requires confirmation.",
            )

        if self._is_sensitive(resolved):
            return PathDecision(
                decision=PathDecisionType.DENY,
                normalized=str(resolved),
                reason="Sensitive path is blocked.",
            )

        if not self._is_within_any_root(resolved, self.allowed_roots):
            return PathDecision(
                decision=PathDecisionType.CONFIRM,
                normalized=str(resolved),
                reason="Path is outside allowed roots; requires confirmation.",
            )

        return PathDecision(decision=PathDecisionType.ALLOW, normalized=str(resolved), reason="Allowed path.")

    def is_within_root(self, path: Path) -> bool:
        try:
            resolved = path.resolve(strict=False)
            return self.classify(resolved).decision == PathDecisionType.ALLOW
        except Exception:
            return False

    def requires_confirmation(self, path: str | Path) -> bool:
        return self.classify(path).decision == PathDecisionType.CONFIRM

    def is_denied(self, path: str | Path) -> bool:
        return self.classify(path).decision == PathDecisionType.DENY

    def decision_for_frontend(self, path: str | Path) -> dict[str, str]:
        decision = self.classify(path)
        return {"decision": decision.decision.value, "normalized": decision.normalized, "reason": decision.reason}
