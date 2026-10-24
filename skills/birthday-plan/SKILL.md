---
name: birthday-plan
description: Plan, organise or celebrate a birthday or birthday party, pick gift ideas, and remember birthdays of family and friends.
---

## How to plan a birthday

1. Ask questions on whose birthday it is and call `search_notes` to find out user's relation 
   to the person. 
2. Ask about the location (city) and date on which the party needs to be planned.
3. Call `get_time` for the location's timezone, and say the local time
   there now and how far it is from the user's own clock.
4. Work out the days left until the birthday from today’s date, and say it first.
5. Suggest a list of activities, restaurants, etc. for a birthday party in that location 
   which remains open at that time.
6. Take confirmation from the user and make a brief plan and then save this plan using `save_note`

## Edge cases

| Situation                         | Do                                                                       |
|-----------------------------------|--------------------------------------------------------------------------|
| No relation to user in the notes  | Ask user explicitly.                                                     |

