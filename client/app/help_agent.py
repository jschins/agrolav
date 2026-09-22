"""Answer questions about using Agrolav from hit terms in the root README."""
from __future__ import annotations

import re
from pathlib import Path

# Dutch and everyday phrases, rewritten onto the English words the hit terms use.
_PHRASES = (
    ("inloggen", "login"),
    ("uitloggen", "logout"),
    ("log ik uit", "logout"),
    ("log out", "logout"),
    ("log ik in", "login"),
    ("right click", "rightclick"),
    ("right-click", "rightclick"),
    ("rechtsklik", "rightclick"),
    ("termen", "terms"),
    ("wachtwoord", "password"),
    ("categorieën", "categories"),
    ("categorieen", "categories"),
    ("categorie", "category"),
    ("jaar wissen", "wipe year"),
    ("boekingen", "bookings"),
    ("boeking", "booking"),
    ("bankafschrift", "download"),
    ("transacties", "transactions"),
    ("herberekenen", "recalculate"),
    ("persoon", "person"),
    ("land", "country"),
    ("centrum", "center"),
)

def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# Brace lines may be HTML comments so the markdown preview does not show them.
_HIDDEN = r"(?:<!--\s*)?"
_HIDDEN_END = r"(?:\s*-->)?"
_HIT_LINE = re.compile(rf"^{_HIDDEN}\{{(?:(?:en|nl):\s*)?([^{{}}]*)\}}{_HIDDEN_END}\s*$")
_DISCARD_LINE = re.compile(
    rf"^{_HIDDEN}\{{discard(?:-(?:en|nl))?:\s*(.*)\}}{_HIDDEN_END}\s*$"
)


def answer_question(question: str, root: Path | None = None) -> dict[str, object]:
    text = (question or "").strip()
    if not text:
        raise ValueError("empty question")
    root = root or repo_root()
    return _answer_from_brackets(text, root) or _miss()


def _answer_from_brackets(question: str, root: Path) -> dict[str, object] | None:
    """Score only `{hit, terms}` lines in the root README. Show the whole section."""
    path = root / "README.md"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    question = _strip_discards(question, _discard_phrases(raw))
    scored: list[tuple[int, str]] = []
    for body, terms in _bracket_entries(raw):
        score = _bracket_score(question, terms)
        if score > 0:
            scored.append((score, body))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return {"answer": "\n\n".join(body for _, body in scored), "sources": ["README.md"]}


def _bracket_entries(text: str) -> list[tuple[str, list[str]]]:
    """One entry per heading. `{en:}` / `{nl:}` lines in it share that body.

    `{discard-en:}` and `{discard-nl:}` are the preamble at the top of the
    file, before the title. They are not part of any section.
    """
    heading_line = ""
    body_lines: list[str] = []
    terms: list[str] = []
    entries: list[tuple[str, list[str]]] = []

    def flush() -> None:
        nonlocal body_lines, terms
        lines = [line for line in body_lines if line.strip() != "---"]
        body = "\n".join(lines).strip()
        if heading_line:
            body = f"{heading_line}\n\n{body}".strip()
        if body and terms:
            entries.append((body, list(terms)))
        body_lines = []
        terms = []

    for line in text.splitlines():
        if _DISCARD_LINE.match(line.strip()):
            continue
        match = _HIT_LINE.match(line.strip())
        if match:
            terms.extend(part.strip() for part in match.group(1).split(",") if part.strip())
            continue
        if line.startswith("#"):
            flush()
            heading_line = line.strip()
            continue
        body_lines.append(line)
    flush()
    return entries


def _discard_phrases(text: str) -> list[str]:
    """Words in the discard lines at the top of the README, before the title."""
    phrases: list[str] = []
    for line in text.splitlines():
        match = _DISCARD_LINE.match(line.strip())
        if not match:
            continue
        phrases.extend(part.strip() for part in match.group(1).split(",") if part.strip())
    phrases.sort(key=len, reverse=True)
    return phrases


def _strip_discards(question: str, phrases: list[str]) -> str:
    haystack = _norm(question)
    for phrase in phrases:
        needle = _norm(phrase).strip()
        if not needle:
            continue
        haystack = re.sub(rf"(?<!\w){re.escape(needle)}(?!\w)", " ", haystack)
    return haystack


_WEIGHT = re.compile(r"^(.*)\[(\d+)\]\s*$")


def _term_weight(term: str) -> tuple[str, int]:
    """`category[3]` counts as 3. A term with no number counts as 1."""
    raw = term.strip()
    match = _WEIGHT.match(raw)
    if not match:
        return raw, 1
    weight = int(match.group(2))
    if weight < 1:
        return match.group(1).strip(), 1
    return match.group(1).strip(), weight


def _bracket_score(question: str, terms: list[str]) -> int:
    haystack = _norm(question)
    best: dict[str, int] = {}
    for term in terms:
        raw, weight = _term_weight(term)
        needle = _norm(raw).strip()
        if not needle:
            continue
        if weight > best.get(needle, 0):
            best[needle] = weight
    score = 0
    for needle, weight in best.items():
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            score += weight
    return score


def _miss() -> dict[str, object]:
    return {
        "answer": "I don't find an answer to that in the README.",
        "sources": [],
    }


def _norm(text: str) -> str:
    lowered = text.lower()
    for src, dst in _PHRASES:
        lowered = lowered.replace(src, dst)
    return lowered

