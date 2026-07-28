"""Verification rules for agent work-status messages.

The chat server cannot prove that an agent executed a natural-language plan.
It can, however, require a reproducible repository checkpoint before allowing
that plan to be presented as progress and routed to other agents.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


_PROGRESS_RE = re.compile(
    r"\b("
    r"em andamento|progresso|conclu[ií]d[oa]|entregue|feito|implementad[oa]|"
    r"commit(?:ado)?|push(?:ed)?|qa(?: visual)?|valid(?:ado|ated)|"
    r"working tree|in progress|completed|done|delivered|implemented|"
    r"committed|verified|tests? (?:pass|green)|tsc green|cargo green"
    r")\b",
    re.IGNORECASE,
)
_COMPLETION_RE = re.compile(
    r"\b(conclu[ií]d[oa]|entregue|feito|commit(?:ado)?|push(?:ed)?|"
    r"qa(?: visual)?|valid(?:ado|ated)|completed|done|delivered|"
    r"committed|verified|tests? (?:pass|green)|tsc green|cargo green)\b",
    re.IGNORECASE,
)
_NEGATED_PROGRESS_RE = re.compile(
    r"\b(?:n[aã]o|not|never|without)\s+(?:foi\s+|was\s+|is\s+|est[aá]\s+)?"
    r"(?:feito|conclu[ií]d[oa]|entregue|implementad[oa]|commit(?:ado)?|"
    r"completed|done|delivered|implemented|committed|verified|validated)\b",
    re.IGNORECASE,
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def looks_like_progress_claim(text: str) -> bool:
    """Return True only for a likely execution/progress assertion."""
    without_negations = _NEGATED_PROGRESS_RE.sub("", text or "")
    return bool(_PROGRESS_RE.search(without_negations))


def _workspace(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        path = Path(value).expanduser().resolve()
    except OSError:
        return None
    return path if path.is_dir() and (path / ".git").exists() else None


def _relative_file(workspace: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    try:
        resolved = (workspace / candidate).resolve()
        resolved.relative_to(workspace)
    except (OSError, ValueError):
        return None
    return resolved


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )


def verify_work_evidence(
    workspace_value: Any,
    evidence: Any,
    *,
    require_commit: bool = False,
) -> tuple[bool, list[dict[str, str]], str]:
    """Verify commit/changed-file evidence without executing agent commands.

    A completed/QA report must reference an existing commit. A live checkpoint
    may instead reference a file that Git currently reports as changed.
    """
    workspace = _workspace(workspace_value)
    if workspace is None:
        return False, [], "workspace must be an existing Git repository"
    if not isinstance(evidence, list) or not evidence:
        return False, [], "attach a commit or a changed_file checkpoint"

    verified: list[dict[str, str]] = []
    has_commit = False
    has_changed_file = False
    for item in evidence:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        value = item.get("value")
        if kind == "commit" and isinstance(value, str) and _SHA_RE.fullmatch(value):
            result = _git(workspace, "rev-parse", "--verify", f"{value}^{{commit}}")
            if result.returncode == 0:
                sha = result.stdout.strip()
                verified.append({"kind": "commit", "value": sha})
                has_commit = True
        elif kind == "changed_file":
            path = _relative_file(workspace, value)
            if path is None:
                continue
            relative = path.relative_to(workspace).as_posix()
            result = _git(workspace, "status", "--porcelain", "--", relative)
            if result.returncode == 0 and result.stdout.strip():
                verified.append({"kind": "changed_file", "value": relative})
                has_changed_file = True

    if require_commit and not has_commit:
        return False, verified, "a completed or QA claim requires a verifiable commit"
    if not has_commit and not has_changed_file:
        return False, verified, "no supplied evidence matches the current repository"
    return True, verified, ""


def classify_work_status(text: str, workspace: Any, evidence: Any) -> tuple[str, dict | None]:
    """Classify a message and attach evidence metadata when it makes a claim."""
    if not looks_like_progress_claim(text):
        return "chat", None
    completed = bool(_COMPLETION_RE.search(text or ""))
    ok, verified, reason = verify_work_evidence(
        workspace,
        evidence,
        require_commit=completed,
    )
    metadata = {
        "work_status": True,
        "verified": ok,
        "workspace": str(workspace or ""),
        "evidence": verified,
        "reason": reason,
    }
    return ("verified_work_status" if ok else "unverified_work_status"), metadata
