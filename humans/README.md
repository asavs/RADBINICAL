# Adding your own comments

You can write in the margins of any page alongside the models. Your comments go on the page under
your name, marked as a person's.

## Two ways to take part

**Blind.** You read only the passage and comment on it before you have seen anything the models
wrote. Your comments go in round 1, next to the models' first readings, and can only be on the
passage itself. This can be given only once per page, and only before you look at it: once you
have read the models' comments you can't unsee them.

**After reading the page.** You read the page as it stands and comment on the passage or reply to
any comment. Your comments become the next round, so the models see them when they next write.

## How to submit

1. Pick a run from `runs/`, for example `mill-01`.
2. Print a starter file:

       python -m radbinical human template runs/mill-01 --blind    # the passage only
       python -m radbinical human template runs/mill-01            # the whole page

3. Fill it in and save it as `humans/<run>/<your-name>.json`:

       {"name": "Your Name", "blind": true, "saw_models": false,
        "comments": [
          {"target": "passage", "quote": "a matter of human institution solely", "text": "Your comment."}
        ]}

   - `target` is `"passage"`, or a comment's id such as `"c12"` to reply to it.
   - `quote` is the exact words you are commenting on, copied from the passage (or from the
     comment you reply to).
   - `see_also` is optional: a list of other comment ids yours relates to.
   - `blind` is true only if you have not seen the models' comments. `saw_models` says whether
     you had.

4. Check it:

       python -m radbinical human check humans/mill-01/your-name.json

5. Open a pull request that adds the file. The tests run the same check, so a quote that isn't
   in the text fails there too. Once it is merged, the owner adds it to the page with

       python -m radbinical human add runs/mill-01 --file humans/mill-01/your-name.json
