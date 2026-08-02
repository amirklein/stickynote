"""Translating a pack into another language.

Worth saying plainly, and the CLI says it too: machine translation is decent
at the sincere pack and poor at the funny one. Timing, idiom and wordplay are
precisely what a translation loses, and a joke that lands flat is worse than
no joke. The output is a normal user pack, editable by hand, because a
native speaker fixing forty lines will beat any prompt.
"""

from __future__ import annotations

from typing import Dict, List

from . import ai, packs

# Only the common ones get a name; anything else is passed to the model as
# written, which works fine for "Brazilian Portuguese" or "Swiss German".
LANGUAGES: Dict[str, str] = {
    "ar": "Arabic",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "zh": "Chinese",
}

_SYSTEM = (
    "You translate short encouraging notifications. Rules: keep each line on "
    "its own line, keep the count and order identical to the input, and keep "
    "each line short enough for a notification. Do not number the lines or "
    "add commentary. Where a joke depends on English wordplay or a cultural "
    "reference, write the closest thing that is actually funny in the target "
    "language rather than a literal translation that is not."
)

# Small enough that one bad batch is cheap to redo, large enough that the
# model keeps a consistent voice across neighbouring lines.
BATCH = 40


def language_name(code: str) -> str:
    return LANGUAGES.get(code.strip().lower(), code.strip())


def translate_lines(lines: List[str], language: str, timeout: float = 120.0) -> List[str]:
    """Translate in batches, keeping line count stable batch by batch."""
    name = language_name(language)
    out: List[str] = []

    for start in range(0, len(lines), BATCH):
        chunk = lines[start:start + BATCH]
        prompt = (
            f"Translate these {len(chunk)} lines into {name}. "
            f"Return exactly {len(chunk)} lines, in the same order.\n\n"
            + "\n".join(chunk)
        )
        reply = ai.complete(_SYSTEM, prompt, max_tokens=4000, timeout=timeout)
        translated = ai.lines_from(reply)

        if len(translated) != len(chunk):
            # Dropping the mismatched batch would silently shorten the pack,
            # so keep the originals and let the caller report the shortfall.
            raise ai.AIError(
                f"expected {len(chunk)} lines back, got {len(translated)}. "
                "Try a smaller batch or a stronger model."
            )
        out.extend(translated)
    return out


def translate_pack(source_id: str, language: str, new_id: str = "",
                   timeout: float = 120.0) -> str:
    source = packs.get(source_id)
    if source is None:
        raise ai.AIError(f"no pack called {source_id!r}")

    lines = source.messages()
    translated = translate_lines(lines, language, timeout)
    pack_id = new_id or f"{source_id}-{language.strip().lower()}"

    packs.write_pack(
        pack_id,
        f"{source.name} ({language_name(language)})",
        f"{source.description} Machine-translated from {source_id}; edit freely.",
        language.strip().lower(),
        translated,
    )
    return pack_id
