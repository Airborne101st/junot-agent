---
name: trip-prep
description: Get ready, prepare, plan or pack for a trip, flight, journey, holiday or travel, and check what to remember before leaving.
---

## How to prepare a trip

1. Read the notes already in your prompt for this trip: where, when, why, and
   who the user is travelling to see. If the destination or date is missing,
   call `search_notes` once with the place or "trip travel flight".
2. Notes that change what to pack or eat are rarely found by a trip search.
   Call `search_notes` once with "allergy allergic health diet medicine", and
   mention each one you apply ("you noted a peanut allergy, so...").
3. Call `get_time` for the destination's timezone, and say the local time
   there now and how far it is from the user's own clock.
4. Give one short checklist, in this order: documents, money, medicine,
   clothes for the occasion, chargers. At most eight lines.
5. End with the single most important thing not to forget, in one sentence.

## Edge cases

| Situation | Do |
|---|---|
| No trip in the notes | Ask where and when, in one question. Don't invent a destination. |
| Trip date has passed | Say so, and ask whether there's a new trip. |
| The user says "remember" a detail | Use `save_note` with one sentence that names the trip and the full date. |
