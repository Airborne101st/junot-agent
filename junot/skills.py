"""Skills: workflows written in markdown, loaded only when they're relevant.

Procedural memory: not facts about you (that's memory.py), but how to do a
kind of task well. Each skill is a folder with a SKILL.md, in the same
format Claude Code and Waku read:

    ---
    name: trip-prep
    description: Prepare, plan or pack for a trip, flight or travel...
    ---
    ## How to prepare a trip
    1. ...

The description is also the trigger. Every turn, each skill's name and
description are compared with the message (cheap); only a skill that matches
has its body put into the prompt. That's progressive disclosure: ten skills
cost ten short descriptions to check, not ten bodies to send.

YOUR CODE (step 8). See docs/steps/08-skills.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Words that appear in almost any request and say nothing about which skill
# it needs. Without them, "can you tell me what the time is" matches any
# skill whose description says "can", "you", "what" and "the".
STOPWORDS: set[str] = {
    "the", "and", "you", "what", "can", "for", "with", "this", "that", "are", "was",
    "have", "has", "had", "from", "your", "yours", "about", "please", "how", "when",
    "where", "who", "why", "which", "will", "would", "could", "should", "not", "but",
    "all", "any", "its", "our", "out", "get", "got", "into", "just", "tell", "make",
    "some", "there", "here", "them", "they", "then", "than", "also", "want", "need",
    "help", "give", "let", "now", "today", "one", "two", "very", "much", "more",
}

# A match needs at least this many shared words: one is often a coincidence
# ("trip" in "how long is the trip?" isn't a request to pack).
MIN_SHARED = 2

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path


def parse_skill(text: str, path: Path) -> Skill | None:
    """A Skill from SKILL.md text, or None if the frontmatter is missing or
    lacks a name or a description."""
    match = FRONTMATTER.match(text)
    if not match:
        return None
    front, body = match.groups()
    fields = {}
    for line in front.splitlines():
        # partition splits on the FIRST colon only: a description may hold more.
        key, colon, value = line.partition(":")
        if colon:
            fields[key.strip()] = value.strip().strip("'\"")
    if not fields.get("name") or not fields.get("description"):
        return None
    return Skill(fields["name"], fields["description"], body.strip(), path)


def load_skills(folder: Path) -> list[Skill]:
    """Every valid */SKILL.md under `folder`, sorted by name. [] if the folder
    doesn't exist. Invalid files are skipped, not fatal."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    skills = []
    for path in folder.glob("*/SKILL.md"):
        skill = parse_skill(path.read_text(encoding="utf-8"), path)
        if skill is not None:
            skills.append(skill)
    return sorted(skills, key=lambda skill: skill.name)


def _words(text: str) -> set[str]:
    """Lowercase words of 3+ letters or digits, stopwords removed."""
    return set(re.findall(r"[a-z0-9]{3,}", text.lower())) - STOPWORDS


def match_skills(skills: list[Skill], message: str, max_skills: int = 2) -> list[Skill]:
    """Skills sharing at least 2 words with the message (in name + description,
    lowercase, 3+ letters, stopwords ignored), most shared words first, at
    most `max_skills`."""
    wanted = _words(message)
    scored = []
    for skill in skills:
        shared = len(wanted & _words(f"{skill.name} {skill.description}"))
        if shared >= MIN_SHARED:
            scored.append((shared, skill))
    # Best first; on a tie, by name, so the same message always loads the same skills.
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [skill for _, skill in scored[:max_skills]]
