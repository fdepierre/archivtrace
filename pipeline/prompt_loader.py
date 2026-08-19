"""Load versioned prompt templates from the repository ``prompts/`` directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_HEADER_RE = re.compile(r"^#\s*(\w+)\s*:\s*(.+)$")
_SYSTEM_RE = re.compile(r"<system>(.*?)</system>", re.DOTALL | re.IGNORECASE)
_USER_TMPL_RE = re.compile(
    r"<user_template>(.*?)</user_template>", re.DOTALL | re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Parsed prompt file: metadata + system text + user template."""

    id: str
    version: int
    path: Path
    system: str
    user_template: str
    headers: dict[str, str]

    def render_user(self, **kwargs: object) -> str:
        """Fill ``{{placeholders}}`` in the user template."""
        text = self.user_template
        for key, value in kwargs.items():
            text = text.replace("{{" + key + "}}", str(value if value is not None else ""))
        # Drop any unreplaced optional placeholders.
        text = re.sub(r"\{\{[a-z_]+\}\}", "", text)
        return text.strip()


def _parse_headers(raw: str) -> tuple[dict[str, str], str]:
    headers: dict[str, str] = {}
    lines = raw.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue
        match = _HEADER_RE.match(line)
        if not match:
            break
        headers[match.group(1)] = match.group(2).strip()
        idx += 1
    body = "\n".join(lines[idx:])
    return headers, body


def _latest_path(prompt_id: str) -> Path:
    matches = sorted(PROMPTS_DIR.glob(f"{prompt_id}.v*.xml.txt"))
    if not matches:
        raise FileNotFoundError(
            f"No prompt file for id={prompt_id!r} under {PROMPTS_DIR}"
        )
    return matches[-1]


@lru_cache(maxsize=32)
def load_prompt(prompt_id: str, *, version: int | None = None) -> PromptTemplate:
    """Load a prompt by id; default = highest ``vN`` file present."""
    if version is None:
        path = _latest_path(prompt_id)
    else:
        path = PROMPTS_DIR / f"{prompt_id}.v{version}.xml.txt"
        if not path.is_file():
            raise FileNotFoundError(path)
    raw = path.read_text(encoding="utf-8")
    headers, body = _parse_headers(raw)
    system_match = _SYSTEM_RE.search(body)
    user_match = _USER_TMPL_RE.search(body)
    if not system_match or not user_match:
        raise ValueError(f"Prompt {path} must contain <system> and <user_template>")
    prompt_id_h = headers.get("id", prompt_id)
    version_h = int(headers.get("version") or version or 1)
    return PromptTemplate(
        id=prompt_id_h,
        version=version_h,
        path=path,
        system=system_match.group(1).strip(),
        user_template=user_match.group(1).strip(),
        headers=headers,
    )


def clear_prompt_cache() -> None:
    """Reset the loader cache (tests / hot reload)."""
    load_prompt.cache_clear()
