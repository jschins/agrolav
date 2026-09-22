"""Answer questions about using Agrolav from the README files and documentation/."""
from __future__ import annotations

import re
from pathlib import Path

_STOP = frozenset(
    """
    a an the of to and or in on for how do i what is are my me we you your this
    that with from when where which can it its be about using use program
    vraag over dit dit programma hoe kan ik de het een van
    """.split()
)

# Dutch and everyday phrases, rewritten onto the English words the docs use.
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

_README_BOOST = 1.8


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def documentation_files(root: Path | None = None) -> list[Path]:
    root = root or repo_root()
    found: list[Path] = []
    readme = root / "README.md"
    if readme.is_file():
        found.append(readme)
    for child in sorted(root.iterdir()):
        nested = child / "README.md"
        if child.is_dir() and nested.is_file():
            found.append(nested)
    docs = root / "documentation"
    if docs.is_dir():
        found.extend(sorted(p for p in docs.glob("*.md") if p.is_file()))
    return found


def answer_question(question: str, root: Path | None = None) -> dict[str, object]:
    text = (question or "").strip()
    if not text:
        raise ValueError("empty question")
    root = root or repo_root()
    tokens = _tokens(text)
    if not tokens:
        return _miss()
    scored: list[dict[str, object]] = []
    for path in documentation_files(root):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        boost = _README_BOOST if rel == "README.md" else 1.0
        for section in _sections(raw):
            score = _score(tokens, section) * boost
            if score < 2:
                continue
            scored.append(
                {
                    "heading": section["heading"],
                    "body": section["body"],
                    "source": rel,
                    "score": score,
                }
            )
    readme = [row for row in scored if row["source"] == "README.md"]
    # Everyday questions stay on the user guide when it covers them.
    pool = readme or [row for row in scored if row["source"] != "README.md"]
    if not pool:
        return _miss()
    pool.sort(key=lambda row: -float(row["score"]))
    picked = pool[:1]
    parts: list[str] = []
    sources: list[str] = []
    for row in picked:
        body = _focus(row["body"], tokens)
        if not body:
            continue
        title = str(row["heading"] or "")
        if title and any(token in _norm(title) for token in tokens):
            parts.append(f"{title}\n\n{body}")
        else:
            parts.append(body)
        if row["source"] not in sources:
            sources.append(row["source"])
    if not parts:
        return _miss()
    return {"answer": "\n\n".join(parts), "sources": sources}


def _miss() -> dict[str, object]:
    return {
        "answer": (
            "I don't find an answer to that in the README or the other documentation."
        ),
        "sources": [],
    }


def _norm(text: str) -> str:
    lowered = text.lower()
    for src, dst in _PHRASES:
        lowered = lowered.replace(src, dst)
    return lowered


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9+-]{1,}", _norm(text))
    return [w for w in words if w not in _STOP]


def _sections(text: str) -> list[dict[str, str]]:
    heading = ""
    buf: list[str] = []
    out: list[dict[str, str]] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if heading or body:
            out.append({"heading": heading, "body": body})

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return out


def _score(tokens: list[str], section: dict[str, str]) -> float:
    heading = _norm(section["heading"])
    body = _norm(section["body"])
    score = 0.0
    for token in tokens:
        if token in heading:
            score += 3
        hits = body.count(token)
        if hits:
            score += min(hits, 3) * 2
    return score


def _focus(body: str, tokens: list[str], limit: int = 700) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paras:
        return ""
    hits = [p for p in paras if any(t in _norm(p) for t in tokens)]
    pool = hits or paras[:1]
    chosen: list[str] = []
    used = 0
    for para in pool:
        if chosen and used + len(para) > limit:
            break
        chosen.append(para[:limit] if not chosen and len(para) > limit else para)
        used += len(chosen[-1])
        if used >= limit:
            break
    return "\n\n".join(chosen)
