"""The question-asking loop: batches of 4-6 questions, answered in one message."""

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .models import FormField, FormSchema

MIN_BATCH = 4
MAX_BATCH = 6
# How many times to ask before leaving a field for the review screen.
MAX_ASKS_REQUIRED = 2
MAX_ASKS_OPTIONAL = 1
SESSION_TTL_SECONDS = 60 * 60


def batch_size(remaining: int) -> int:
    """Split the remaining questions into even batches of 4-6.

    7 -> 4 then 3, 8 -> 4+4, 13 -> 5+4+4. Fewer than 4 left -> ask them all.
    """
    if remaining <= MAX_BATCH:
        return remaining
    batches = math.ceil(remaining / MAX_BATCH)
    return max(MIN_BATCH, math.ceil(remaining / batches))


_TRUE = {"true", "yes", "y", "1", "on", "checked", "x"}
_FALSE = {"false", "no", "n", "0", "off", "unchecked"}


def _match_option(value: str, options: list[str]) -> str | None:
    v = value.strip().lower()
    for o in options:
        if o.lower() == v:
            return o
    hits = [o for o in options if v and (v in o.lower() or o.lower() in v)]
    return hits[0] if len(hits) == 1 else None


def normalize(f: FormField, value: Any) -> Any | None:
    """Coerce an AI-extracted value to what the field accepts, or None if it doesn't fit."""
    if value is None:
        return None
    if f.type == "checkbox" and f.options:
        items = value if isinstance(value, list) else re.split(r"\s*[,;]\s*", str(value))
        picked = [m for m in (_match_option(str(i), f.options) for i in items) if m]
        return list(dict.fromkeys(picked)) or None
    if f.type == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        return True if s in _TRUE else False if s in _FALSE else None
    if isinstance(value, (list, dict)):
        value = ", ".join(map(str, value)) if isinstance(value, list) else None
        if value is None:
            return None
    s = str(value).strip()
    if not s:
        return None
    if f.options and f.type in ("choice", "dropdown", "scale"):
        return _match_option(s, f.options)
    if f.type == "date":
        return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
    if f.type == "time":
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None
    if f.type == "number":
        try:
            float(s.replace(",", ""))
        except ValueError:
            return None
        return s.replace(",", "")
    return s


@dataclass
class Session:
    """One request being filled in. Lives in memory only; nothing is written to disk."""

    form: FormSchema
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    answers: dict[str, Any] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    asks: dict[str, int] = field(default_factory=dict)
    current_batch: list[str] = field(default_factory=list)
    done: bool = False
    touched: float = field(default_factory=time.time)

    def apply(self, raw_answers: dict[str, Any], skipped: list[str]) -> list[str]:
        """Store extracted answers. Returns ids that were rejected as invalid."""
        rejected = []
        for fid, raw in raw_answers.items():
            f = self.form.field(fid)
            if f is None:
                continue
            value = normalize(f, raw)
            if value is None:
                rejected.append(fid)
            else:
                self.answers[fid] = value
                self.skipped.discard(fid)
        for fid in skipped:
            if self.form.field(fid) and fid not in self.answers:
                self.skipped.add(fid)
        return rejected

    def unanswered(self) -> list[FormField]:
        return [f for f in self.form.fields if f.id not in self.answers and f.id not in self.skipped]

    def pending(self) -> list[FormField]:
        """Fields still worth asking about, in form order."""
        out = []
        for f in self.unanswered():
            limit = MAX_ASKS_REQUIRED if f.required else MAX_ASKS_OPTIONAL
            if self.asks.get(f.id, 0) < limit:
                out.append(f)
        return out

    def next_batch(self) -> list[FormField]:
        pending = self.pending()
        batch = pending[: batch_size(len(pending))]
        self.current_batch = [f.id for f in batch]
        for f in batch:
            self.asks[f.id] = self.asks.get(f.id, 0) + 1
        return batch

    def missing_required(self) -> list[FormField]:
        return [f for f in self.form.fields if f.required and f.id not in self.answers]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def add(self, s: Session) -> Session:
        self._prune()
        self._sessions[s.id] = s
        return s

    def get(self, sid: str) -> Session | None:
        self._prune()
        s = self._sessions.get(sid)
        if s:
            s.touched = time.time()
        return s

    def drop(self, sid: str) -> None:
        self._sessions.pop(sid, None)

    def _prune(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        for sid in [k for k, s in self._sessions.items() if s.touched < cutoff]:
            del self._sessions[sid]
