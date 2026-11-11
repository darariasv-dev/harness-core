"""Section E, §0.5 boundary discipline: harness-core must stay domain-agnostic. A symbol
whose name or docstring carries a job-search-specific word (job/listing/resume/employer/
salary/greenhouse/ashby/lever/workday/fact) belongs in the PROJECT's adapter, never here --
this is the guardrail that keeps that true as the package grows, not just a one-time check.

Run this FIRST, before adding real content to a new harness_core module -- it's meant to be
the thing that catches a domain word creeping in during extraction, not something fixed up
after the fact."""
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).parent.parent / "harness_core"

# Case-insensitive, whole-word matched. "cache"/"router"/"policy" etc. are fine -- these are
# the SPECIFIC nouns from this project's own job-search domain, not generic engineering terms.
_DOMAIN_WORDS = (
    "job", "listing", "resume", "employer", "salary",
    "greenhouse", "ashby", "lever", "workday",
    "fact",
)
_DOMAIN_WORD_RE = re.compile(r"\b(" + "|".join(_DOMAIN_WORDS) + r")\b", re.IGNORECASE)

# A handful of unavoidable false positives (English words that happen to contain a domain
# word as a substring, already excluded by \b word-boundary matching, or genuine incidental
# uses worth an explicit, reviewed exception -- e.g. a comment citing this very rule).
_ALLOWED_LINE_SUBSTRINGS = (
    "domain word",  # this file's own docstring/comments, and any module citing this rule
    "job-search",   # the generic project-description phrase, not a job/listing data concept
)


def _python_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def test_harness_core_package_exists_and_has_files():
    files = _python_files()
    assert files, f"no .py files found under {PACKAGE_ROOT} -- package not built yet"


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(PACKAGE_ROOT.parent)))
def test_no_domain_words_in_harness_core(path: Path):
    text = path.read_text()
    offending_lines = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(allowed in line.lower() for allowed in _ALLOWED_LINE_SUBSTRINGS):
            continue
        if _DOMAIN_WORD_RE.search(line):
            offending_lines.append((lineno, line.strip()))
    assert not offending_lines, (
        f"{path} contains job-search-domain word(s) -- belongs in the project adapter, "
        f"not harness-core:\n" + "\n".join(f"  line {n}: {l}" for n, l in offending_lines)
    )
