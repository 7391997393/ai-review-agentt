# BUSINESS_VALUE.md

**Read this first:** every number below is a model built on stated assumptions. None of it is
measured. Replace the assumptions with your team's data (and the cost with the real model
usage from a pilot) before presenting it as a result.

## Assumptions (edit these)

| Input | Value | Note |
|-------|-------|------|
| Developers | 50 | example team |
| PRs per developer per month | 4 | 200 PRs per month |
| Reviewer time per PR | 30 min | first read plus comments |
| Share of that time on mechanical checks | 30% | secrets, obvious bugs, missing tests, style-level issues |
| Share of mechanical checks the agent covers | 60% | assumption, to be measured in the pilot |
| Loaded cost per engineer hour | 60 USD | placeholder |
| Agent run cost per PR | 0.50 USD | placeholder: model tokens plus Actions minutes |
| Build and rollout effort | 80 hours | one-time |

## Time savings

Minutes saved per PR = 30 x 30% x 60% = **5.4 minutes** of reviewer time.

Per month: 200 x 5.4 = 1,080 min = **18 hours**. Per year: **216 hours**.

Faster first feedback is a separate benefit the model does not price: the author gets the
mechanical issues minutes after the push, so rework happens while the context is fresh.

## Reduction in review effort

Mechanical checks are 30% of review time and the agent covers 60% of them, so overall
review effort falls by about **18%** (30% x 60%) under these assumptions. Reviewers
keep the work that needs judgment: design, intent and trade-offs.

## Security improvements (qualitative)

- Every PR gets the same security pass, regardless of reviewer availability or fatigue.
- Hard-coded secrets, injection patterns and unsafe input handling are flagged before merge.
- Severity and confidence are shown on each finding, so reviewers can triage.

The agent is a first-pass screen, not a replacement for static analysis or security review. It
can miss issues and can report false positives; measure both in the pilot.

## Developer productivity

- Less waiting: feedback arrives in the Actions run time, not the reviewer queue.
- Fewer review round trips for mechanical fixes.
- No comment clutter: duplicates are suppressed and fixed threads close themselves.

## Estimated ROI (illustrative)

| Item | Amount |
|------|--------|
| Annual time saved | 216 h x 60 USD = **12,960 USD** |
| Annual run cost | 200 PRs x 12 months x 0.50 USD = **1,200 USD** |
| One-time build and rollout | 80 h x 60 USD = **4,800 USD** |
| Net benefit, year 1 | 12,960 - 1,200 - 4,800 = **6,960 USD** |
| ROI, year 1 | 6,960 / (1,200 + 4,800) = **116%** |
| Payback | about 5 months (4,800 / (1,080 - 100) per month) |

Sensitivity: at 30% coverage (half the assumed value) the annual saving is 6,480 USD, which
gives a year-1 ROI of 8%. At 90% coverage it is 19,440 USD. The result is most sensitive to
coverage and to the number of PRs, so those are the two things to measure.

## How to turn this into evidence (pilot plan)

1. Run the agent on 2 to 3 real repositories for 2 weeks.
2. Track per PR: findings posted, findings accepted (fixed) versus dismissed, time to first
   feedback, and model cost from the provider dashboard.
3. Accepted share is the measured precision. Replace "60% coverage" and "0.50 USD" with it.
