# How the judge is built and measured

## The loop

1. Agents do the work with the playbook and save it on the firm's machine.
2. taskout picks jobs at random (every one until 20 in 4 weeks, then 1 in 10) for the playbook owner's review.
   A sent-back or rejected verdict always says what went wrong: a rule not followed, a rule followed but wrong,
   no rule for it, or something else.
3. The judge learns from those verdicts (GEPA), here.
4. The judge reviews every job; what went wrong becomes proposed rule changes.
5. A person approves the changes, publishes, and tries the new version on a share of jobs.

## The data

- Only jobs picked at random. Flagged jobs are reviewed too, but they are skewed towards failures.
- A fixed third, by a hash of the job id, is held out. GEPA never sees it. Of the rest, about 3 in 10 are GEPA's
  validation set (it keeps the instructions that do best there) and the others its training set.
- Each example: the rules of the version the job ran on, the work, the person's verdict and cause, and their notes
  when they wrote some in `review.md` next to the work.

## The score

Per job: 1.0 when the judge's outcome (accepted as is, accepted with changes, not accepted) and cause match the
person's; 0.7 for the same outcome with a different cause; 0 otherwise. GEPA reads, for each miss, what the
person said and what the judge said, and rewrites the instructions. Its reflection prompt asks for general criteria
only: no client names, figures, dates, references or quotes. The result is scanned for identifier shapes.

## The bar (checked by taskout)

On the held-out jobs, recomputed by taskout from its own verdicts: at least 10 jobs, at least 2 of them sent back
or rejected, agreement on the outcome in at least 8 of 10, and at least 8 of 10 sent-back or rejected jobs caught.
Once approved, taskout keeps comparing the judge with people on the jobs both reviewed. Below 8 in 10 on at least
10 such jobs, the judge is marked as drifting: its verdicts stop counting until it is rebuilt.

## Rules and the judge never learn from the same jobs

`propose_rules.py` leaves out every job in the judge's `trained_on`, and taskout refuses a proposal that cites
one. A new rule version is promoted only by a person, from people's verdicts on the trial.
