"""Step 8: skills. These tests are the spec.

    uv run pytest tests/test_step08_skills.py -v

A new workflow is a markdown file in skills/<name>/SKILL.md. No Python.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from junot.config import PROJECT_SKILLS
from junot.session import Session
from junot.skills import STOPWORDS, Skill, load_skills, match_skills, parse_skill

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))

PACKING = """---
name: packing-list
description: Make a packing list for a trip or holiday.
---

## How
1. Check the weather.
"""


def _write(folder: Path, name: str, text: str) -> Path:
    (folder / name).mkdir(parents=True, exist_ok=True)
    path = folder / name / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def _skill(name: str, description: str) -> Skill:
    return Skill(name, description, f"body of {name}", Path(f"{name}/SKILL.md"))


# ---- parse_skill ---------------------------------------------------------------

def test_a_skill_has_a_name_a_description_and_a_body():
    skill = parse_skill(PACKING, Path("packing-list/SKILL.md"))
    assert skill.name == "packing-list"
    assert skill.description == "Make a packing list for a trip or holiday."
    assert skill.body == "## How\n1. Check the weather."
    assert skill.path == Path("packing-list/SKILL.md")


def test_quotes_around_values_are_removed():
    text = '---\nname: "packing-list"\ndescription: \'Make a packing list.\'\n---\nbody'
    skill = parse_skill(text, Path("x"))
    assert (skill.name, skill.description) == ("packing-list", "Make a packing list.")


def test_no_frontmatter_is_not_a_skill():
    assert parse_skill("## Just some notes\nNo frontmatter here.", Path("x")) is None


def test_a_missing_name_or_description_is_not_a_skill():
    assert parse_skill("---\nname: x\n---\nbody", Path("x")) is None
    assert parse_skill("---\ndescription: y\n---\nbody", Path("x")) is None


def test_a_colon_inside_the_description_is_kept():
    skill = parse_skill("---\nname: x\ndescription: Plan a day: morning, noon, night.\n---\nb", Path("x"))
    assert skill.description == "Plan a day: morning, noon, night."


# ---- load_skills ---------------------------------------------------------------

def test_every_skill_folder_is_loaded_sorted_by_name(tmp_path):
    _write(tmp_path, "zebra", "---\nname: zebra\ndescription: z z\n---\nz")
    _write(tmp_path, "packing-list", PACKING)
    assert [s.name for s in load_skills(tmp_path)] == ["packing-list", "zebra"]


def test_an_invalid_skill_is_skipped_not_fatal(tmp_path):
    _write(tmp_path, "packing-list", PACKING)
    _write(tmp_path, "broken", "no frontmatter at all")
    assert [s.name for s in load_skills(tmp_path)] == ["packing-list"]


def test_a_missing_folder_has_no_skills(tmp_path):
    assert load_skills(tmp_path / "nope") == []


# ---- match_skills: the description is the trigger ------------------------------

def test_two_shared_words_match_in_any_case():
    skills = [_skill("packing-list", "Make a packing list for a trip or holiday.")]
    assert [s.name for s in match_skills(skills, "Can you do a PACKING LIST?")] == ["packing-list"]


def test_one_shared_word_is_not_enough():
    skills = [_skill("packing-list", "Make a packing list for a trip or holiday.")]
    assert match_skills(skills, "How long is the trip?") == []


def test_the_name_counts_as_well_as_the_description():
    skills = [_skill("trip-prep", "Get ready to leave.")]
    assert match_skills(skills, "help me prep for the trip") != []


def test_stopwords_never_count():
    """Shared "can", "you", "what", "the" are not evidence of anything."""
    assert {"the", "and", "you", "what", "can", "for"} <= STOPWORDS
    skills = [_skill("weekend", "Tell you what the plan can be for the weekend.")]
    assert match_skills(skills, "Can you tell me what the time is?") == []


def test_the_best_match_comes_first_and_at_most_two_load():
    skills = [_skill("a", "trip flight"),
              _skill("b", "trip flight packing hotel"),
              _skill("c", "trip packing"),
              _skill("d", "cooking recipes")]
    matched = match_skills(skills, "trip flight packing hotel tomorrow")
    assert [s.name for s in matched] == ["b", "a"] or [s.name for s in matched] == ["b", "c"]
    assert len(matched) == 2


# ---- the Session puts a matching skill in the prompt -----------------------------

def _session(tmp_path, skills_dir, **kwargs) -> Session:
    return Session(tmp_path, "m", clock=lambda: NOW, skills_dir=skills_dir, **kwargs)


def test_without_skills_nothing_changes(tmp_path):
    plain = Session(tmp_path, "m", clock=lambda: NOW).build_system()
    assert Session(tmp_path, "m", clock=lambda: NOW).build_messages("pack my packing list")[0]["content"] == plain


def test_a_matching_skill_puts_its_body_in_the_prompt(tmp_path):
    skills = tmp_path / "skills"
    _write(skills, "packing-list", PACKING)
    system = _session(tmp_path, skills).build_messages("Make me a packing list please")[0]["content"]
    assert "packing-list" in system
    assert "1. Check the weather." in system


def test_a_skill_that_doesnt_match_adds_nothing(tmp_path):
    skills = tmp_path / "skills"
    _write(skills, "packing-list", PACKING)
    session = _session(tmp_path, skills)
    assert session.build_messages("What is 17 times 4?")[0]["content"] == session.build_system()


def test_a_new_skill_works_on_the_next_turn_without_a_restart(tmp_path):
    """Like SOUL.md: the folder is read every turn, so adding a file is enough."""
    skills = tmp_path / "skills"
    skills.mkdir()
    session = _session(tmp_path, skills)
    assert "Check the weather" not in session.build_messages("packing list?")[0]["content"]
    _write(skills, "packing-list", PACKING)
    assert "Check the weather" in session.build_messages("packing list?")[0]["content"]


def test_the_match_is_reported_to_the_observer(tmp_path):
    skills = tmp_path / "skills"
    _write(skills, "packing-list", PACKING)
    events = []
    session = _session(tmp_path, skills, observer=lambda kind, event: events.append((kind, event)))
    session.build_messages("packing list for Pune")
    session.build_messages("17 times 4")
    assert events == [("skills", {"matched": ["packing-list"]}), ("skills", {"matched": []})]


# ---- the skills shipped in this repo ------------------------------------------------

def test_every_shipped_skill_is_valid_and_named_after_its_folder():
    """A CI-style check, like waku's validate_skills.py: a broken SKILL.md
    would otherwise be skipped silently and never load."""
    files = sorted(PROJECT_SKILLS.glob("*/SKILL.md"))
    assert files, "ship at least one skill"
    for path in files:
        skill = parse_skill(path.read_text(encoding="utf-8"), path)
        assert skill is not None, f"{path} has no valid frontmatter"
        assert skill.name == path.parent.name, f"{path}: name must match its folder"
        assert len(skill.description) > 30, f"{path}: the description is the trigger; say when to use it"


def test_trip_prep_loads_for_a_trip_and_not_for_arithmetic():
    shipped = load_skills(PROJECT_SKILLS)
    assert "trip-prep" in [s.name for s in match_skills(shipped, "Help me pack for my trip to Pune")]
    assert match_skills(shipped, "What is 17 times 4?") == []
