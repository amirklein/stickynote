"""Optional model access, used for writing and translating notes.

Everything here is opt-in and must fail soft. A missing key, a rate limit or
an outage degrades to the bundled packs; it never degrades to silence. That
constraint is why generation is a batch command by default rather than part
of the delivery path — see brew.py.

HTTP goes through urllib so the stdlib-only promise survives, which matters
because this runs under the system python from a launchd job with no
virtualenv in sight.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import paths


class AIError(RuntimeError):
    pass


# Provider differences are small enough to describe rather than subclass.
PROVIDERS = {
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "env": ("OPENAI_API_KEY",),
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-3-5-haiku-latest",
        "env": ("ANTHROPIC_API_KEY",),
    },
}


@dataclass
class Credentials:
    provider: str = "openai"
    api_key: str = ""
    model: str = ""
    base_url: str = ""

    @property
    def url(self) -> str:
        return self.base_url or PROVIDERS[self.provider]["url"]

    @property
    def resolved_model(self) -> str:
        return self.model or PROVIDERS[self.provider]["model"]


def load_credentials() -> Optional[Credentials]:
    """From ai.json, else the provider's usual environment variable."""
    path = paths.ai_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AIError(f"could not read {path}: {exc}")
        provider = str(raw.get("provider", "openai")).lower()
        if provider not in PROVIDERS:
            raise AIError(f"unknown provider {provider!r}; try {', '.join(PROVIDERS)}")
        key = str(raw.get("api_key", "")) or _from_env(provider)
        if key:
            return Credentials(provider, key, str(raw.get("model", "")),
                               str(raw.get("base_url", "")))

    for provider in PROVIDERS:
        key = _from_env(provider)
        if key:
            return Credentials(provider, key)
    return None


def _from_env(provider: str) -> str:
    for name in PROVIDERS[provider]["env"]:
        if os.environ.get(name):
            return os.environ[name]
    return os.environ.get("STICKYNOTE_AI_KEY", "")


def save_credentials(provider: str, api_key: str, model: str = "") -> None:
    """Write ai.json readable only by its owner."""
    if provider not in PROVIDERS:
        raise AIError(f"unknown provider {provider!r}; try {', '.join(PROVIDERS)}")

    path = paths.ai_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with the right mode from the start; writing then chmod-ing leaves
    # the key world-readable for the moment in between.
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump({"provider": provider, "api_key": api_key, "model": model},
                  out, indent=2)
        out.write("\n")
    os.chmod(path, 0o600)


def configured() -> bool:
    try:
        return load_credentials() is not None
    except AIError:
        return False


def _request(creds: Credentials, system: str, prompt: str,
             max_tokens: int, timeout: float) -> str:
    if creds.provider == "anthropic":
        body: Dict = {
            "model": creds.resolved_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": creds.api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        body = {
            "model": creds.resolved_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {creds.api_key}",
        }

    request = urllib.request.Request(
        creds.url, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise AIError(f"{creds.provider} returned {exc.code}: {detail}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AIError(f"could not reach {creds.provider}: {exc}")

    try:
        if creds.provider == "anthropic":
            return "".join(part.get("text", "") for part in payload["content"])
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AIError(f"unexpected response shape from {creds.provider}")


def complete(system: str, prompt: str, max_tokens: int = 2000,
             timeout: float = 60.0) -> str:
    creds = load_credentials()
    if creds is None:
        raise AIError(
            "no API key. Run `stickynote ai login`, or set OPENAI_API_KEY "
            "or ANTHROPIC_API_KEY."
        )
    return _request(creds, system, prompt, max_tokens, timeout)


# A bullet or a number, at the start of a line: "1. ", "12) ", "- ", "* ".
_BULLET = re.compile(r"^\s*(?:[-*•]\s+|\d{1,3}[.)]\s+)")


def lines_from(text: str) -> List[str]:
    """Pull usable one-liners out of a model's reply.

    Models number things, wrap them in quotes, and add a sentence of
    introduction however firmly you ask them not to, so parse defensively
    rather than trusting the format. A preamble that reads like a note will
    still get through, which is what `brew --review` is for.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "```")):
            continue

        stripped = _BULLET.sub("", line)
        while stripped != line:
            line, stripped = stripped, _BULLET.sub("", stripped)

        line = line.strip().strip('"').strip("'").strip()
        # A trailing colon means a heading, not a note.
        if line.endswith(":"):
            continue
        if 8 <= len(line) <= 200:
            out.append(line)
    return out
