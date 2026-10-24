# Step 8: skills

**Goal:** a new workflow is a markdown file, not code.

Memory (steps 5–7) holds facts *about you*. A skill holds *how to do a kind
of task well*: the steps, the order, the edge cases. Waku calls this
procedural memory, and uses the same format Claude Code does
(`waku/memory/procedural/loader.py`):

```
skills/trip-prep/SKILL.md
---
name: trip-prep
description: Get ready, prepare, plan or pack for a trip, flight, journey, ...
---
## How to prepare a trip
1. Read the notes already in your prompt for this trip ...
```

**The description is the trigger.** Every turn, each skill's name and
description are compared with your message: cheap, a few words each. Only a
skill that matches has its **body** put into the system prompt. That's
**progressive disclosure**: twenty skills cost twenty short descriptions to
check, not twenty bodies to send on every call.

## What a skill did, measured

A reference solution, Gemini, a copy of your notes plus the Pune trip and
the peanut allergy, and the question "Help me get ready for my trip":

| Run | What changed | Result |
|---|---|---|
| 1 | first version of `trip-prep` | **skill didn't load.** "get ready" isn't in the description; only "trip" matched. A long generic list, no local time, no allergy. |
| 2 | added "Get ready" to the description | skill loaded: `get_time` for Pune, the checklist in order, five lines, one closing sentence. **Still no allergy**: the gate searched trip words, which never find "allergic to peanuts". |
| 3 | step 2 now says *search_notes "allergy allergic health diet medicine"* | `search_notes` for health, "you noted a peanut allergy… your allergy medication or EpiPen". |

Every fix was an edit to a markdown file. That's the point of the step: you
can change *how* Junot works without touching Python.

Two lessons came out of it, both from earlier steps:
- **A keyword trigger only fires on the words people actually say** (step 5's
  "sibling" vs "brother", again). Write descriptions with the verbs and
  nouns you'd use, including the casual ones ("get ready", not only "prepare").
- **A skill can direct retrieval.** The gate searches for what the message is
  about. A skill knows what else the task needs, and can ask for it.

**You write:**

| File | What |
|---|---|
| `junot/skills.py` | `STOPWORDS`, `parse_skill`, `load_skills`, `match_skills` |
| `junot/session.py` | `Session` takes `skills_dir`, and adds matching skills to the prompt |
| `skills/<your-skill>/SKILL.md` | **one skill of your own.** No code. |

Already done for you: `settings.skills_dir` (the repo's `skills/` folder, or
`JUNOT_SKILLS`), the example `skills/trip-prep/`, a `[skill]` line in the
REPL, and skills in `show_trace`.

**Done when:**

```bash
uv run pytest -v
```

passes all 152 tests, and a skill **you** wrote (say `skills/birthday-plan/`)
shows a `[skill] birthday-plan` line in the REPL and visibly changes the
answer.

## 1. `parse_skill(text, path)`

Frontmatter is the block between the first two `---` lines:

```python
match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
```

`re.DOTALL` lets `.` match newlines, so `(.*)` takes the whole body. No match:
return `None`. Each frontmatter line is `key: value`. Split on the **first**
colon only (`line.partition(":")`), because a description can contain colons.
Strip spaces and surrounding quotes from the value. Missing `name` or
`description`: return `None`. The body is `group(2)`, stripped.

## 2. `load_skills(folder)`

`folder.glob("*/SKILL.md")`: one level of folders, each with a SKILL.md. Parse
each; skip the ones that return `None`; sort by name. A folder that doesn't
exist means no skills, not an error (`folder.is_dir()`).

## 3. `match_skills(skills, message, max_skills=2)`

Words are lowercase runs of 3+ letters or digits:
`set(re.findall(r"[a-z0-9]{3,}", text.lower())) - STOPWORDS`. A skill's score
is how many words its name plus description share with the message (set
intersection, `&`). Keep skills scoring **2 or more**, best first; on a tie,
by name, so the order is the same every time. At most `max_skills`.

`STOPWORDS` is yours to write: the words that appear everywhere and mean
nothing ("the", "and", "you", "what", "can", "for", ...). A test checks that
"Can you tell me what the time is?" doesn't trigger a skill whose
description happens to say "can", "you", "what" and "the".

Why 2 and not 1? One shared word is often a coincidence ("trip" in "how long
is the trip?" isn't a request to pack). Two is still cheap evidence. It's
the same threshold as Waku.

## 4. The Session

`Session(..., skills_dir=None)`. In `build_system(user_message)`, after the
memory section, when `skills_dir` is set and there's a message:

1. `load_skills(self.skills_dir)`, **every turn**, like SOUL.md. A skill you
   add while the REPL runs works on your next message.
2. `match_skills(...)`, and report `observer("skills", {"matched": [names]})`.
   Report it even when nothing matched, so the trace shows the check happened.
3. For each match, add a section with the skill's name and body, introduced
   as instructions to follow for this request.

## 5. Your own skill

Pick a task you'd really ask Junot to do, using what it can do today: the
clock, `get_time`, notes. Some ideas: plan a birthday from what's saved about
someone, a morning brief, prepare for a meeting that's in the notes. Copy
`skills/trip-prep/` and change it:

- **The description first.** Write it with the words you'd actually type.
  Then check it: does your real request share 2+ non-stopwords with it?
- Numbered steps, each one a thing the model can actually do with its tools.
- An edge-case table: what to do when the notes don't have what's needed.

Then test it in the REPL, and keep editing the file until the answer is the
one you want. The `[skill]` line tells you whether it loaded.

## After it passes, answer these

1. Your skill's description is its only trigger. Write down three ways you
   might ask for it. How many of them actually load it? What does that say
   about keyword triggers, and what would a step-6-style gate for skills cost?
2. A skill and SOUL.md both shape the answer. When they disagree (SOUL says
   "always answer in 1700s English", a skill says "at most eight lines"),
   which wins, and why? Where should each kind of instruction live?
3. Skills are in the repo (committed), SOUL.md and notes are in `data/`
   (ignored). Why the difference? Is there a skill you'd want to keep private?
4. Waku's `create_skill` tool lets the agent write its own SKILL.md when the
   user teaches it a workflow, but only after the user says yes. What could go
   wrong if it didn't ask?
