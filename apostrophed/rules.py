"""Load the contraction rule set from a TSV data file.

Rules are pure data (see ``data/rules.tsv``): a curated list of "safe"
contractions whose apostrophe-less spelling is not itself a real word, plus the
standalone ``i`` -> ``I``. Kept out of code so it can be edited without a
redeploy of the daemon.
"""

from __future__ import annotations

from pathlib import Path


def load_rules(path: str | Path) -> dict[str, str]:
    """Parse a rules TSV into ``{trigger: replacement}``.

    Skips blank lines and ``#`` comments. Each remaining line must be exactly
    ``<trigger>\\t<replacement>`` (one tab). Triggers must be lowercase and
    unique.

    Raises ``ValueError`` on a malformed line (not exactly one tab), a
    non-lowercase trigger, or a duplicate trigger.
    """
    rules: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"line {lineno}: expected '<trigger>\\t<replacement>', got {raw!r}")
        trigger, replacement = parts[0], parts[1]
        if trigger != trigger.lower():
            raise ValueError(f"line {lineno}: trigger {trigger!r} is not lowercase")
        if trigger in rules:
            raise ValueError(f"line {lineno}: duplicate trigger {trigger!r}")
        rules[trigger] = replacement
    return rules
