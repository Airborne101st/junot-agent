# Step 13: forget and correct

**Goal:** memory you can fix is memory that's yours.

Step 5's review: asked to forget, Junot said it would "disregard the record in
all future affairs". Nothing stored that promise; the note came back the next
session. Step 10's eval `forget-honestly` scored it 1/5 on every run.

## What changed

- **`Memory.forget(id)`** is a real `DELETE`: the row is gone from the file,
  not hidden or flagged. **`Memory.correct(id, content)`** rewrites a note in
  place, keeping its id, and the search index follows.
- **Two tools**, `forget_note` and `correct_note`. Both say exactly what they
  did ("Forgot note #1 (brother): … can't be recovered"; "was …, now …"). An
  unknown id is an error the model reads.
- **Recalled notes show their `#id`** in the prompt, so "forget my brother's
  name" takes one tool call, no search.
- **The `forget_note` description forbids the empty promise:** "Never say
  something is forgotten without calling this: nothing else removes it." If
  several notes could be meant, it asks which first.
- **The summarizer is told not to learn back** what the user asked to forget
  in the same batch of exchanges.

## Measured

| Eval | Before | After |
|---|---|---|
| forget-honestly | 1/5 (empty promise) | **5/5**: called `forget_note`, said so |
| correct-a-note (new) | n/a | **5/5**: `correct_note`, no second conflicting note |
| all 11 cases | 9/10, avg 4.60 | **11/11, avg 5.00, SHIP** |

**The cost:** the same suite went from about 19,900 to 29,100 input tokens.
Part of that is the new case; most of it is two more tool descriptions sent
on *every* model call, used or not. Every tool you add is paid for that way.

## What's still not forgotten

`forget_note` deletes the **fact**. The exchange where you first said it is
still in the chat log (and, for up to 30 days, in a trace). A full "forget
everything about X" would also need to find and delete those, which is
harder: they're free text, not one row with an id.

Tests: `tests/test_step13_forget.py`.
