"""Answer questions about using Agrolav from hit terms in the root README."""
from __future__ import annotations

import re
from pathlib import Path

# Dutch and everyday phrases, rewritten onto the English words the hit terms use.
_PHRASES = (
    ("log in", "login"),
    ("inloggen", "login"),
    ("uitloggen", "logout"),
    ("log ik uit", "logout"),
    ("log out", "logout"),
    ("log ik in", "login"),
    ("right click", "rightclick"),
    ("right-click", "rightclick"),
    ("rechtsklik", "rightclick"),
    ("edit terms", "terms"),
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


_HIT_LINE = re.compile(r"^\{(?:(?:en|nl):\s*)?([^{}]*)\}\s*$")
_DISCARD_LINE = re.compile(r"^\{discard(?:-(?:en|nl))?:\s*(.*)\}\s*$")


def answer_question(question: str, root: Path | None = None) -> dict[str, object]:
    text = (question or "").strip()
    if not text:
        raise ValueError("empty question")
    root = root or repo_root()
    return _answer_from_brackets(text, root) or _miss()


def _answer_from_brackets(question: str, root: Path) -> dict[str, object] | None:
    """Score only `{hit, terms}` lines in the root README. Show their paragraphs."""
    path = root / "README.md"
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    best = 0
    winners: list[str] = []
    question = _strip_discards(question, _discard_phrases(raw))
    for body, terms in _bracket_entries(raw):
        score = _bracket_score(question, terms)
        if score <= 0:
            continue
        if score > best:
            best = score
            winners = [body]
        elif score == best:
            winners.append(body)
    if not winners:
        return None
    return {"answer": "\n\n".join(winners), "sources": ["README.md"]}


def _bracket_entries(text: str) -> list[tuple[str, list[str]]]:
    heading = ""
    buf: list[str] = []
    entries: list[list] = []

    def take(raw_terms: str) -> None:
        nonlocal buf
        terms = [part.strip() for part in raw_terms.split(",") if part.strip()]
        lines = [line for line in buf if line.strip() != "---"]
        body = "\n".join(lines).strip()
        buf = []
        if terms and not body and entries:
            entries[-1][1].extend(terms)
            return
        if not body or not terms:
            return
        if heading and not body.lower().startswith(heading.lower()):
            body = f"{heading}\n\n{body}"
        entries.append([body, terms])

    for line in text.splitlines():
        if _DISCARD_LINE.match(line.strip()):
            continue
        match = _HIT_LINE.match(line.strip())
        if match:
            take(match.group(1))
            continue
        if line.startswith("#"):
            buf = []
            heading = line.lstrip("#").strip()
            continue
        buf.append(line)
    return [(body, terms) for body, terms in entries]


def _discard_phrases(text: str) -> list[str]:
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


def _bracket_score(question: str, terms: list[str]) -> int:
    haystack = _norm(question)
    score = 0
    for term in terms:
        needle = _norm(term).strip()
        if not needle:
            continue
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            score += 1 + needle.count(" ")
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

