# How Motif ranks themes

Every theme gets a **priority score from 0 to 100**. Each point of that score can be traced to a signal, and each
signal to the rows of data behind it. No AI model chooses a number: models read text and name themes; the ranking is
arithmetic on stored data. The code is `app/core/scoring.py`; the screen is **Review & edit → Why it ranked here**.

## The signals

Each signal answers a question a product manager would ask, and is only used when the data can answer it honestly.

| Signal | Question it answers | Scenario that needs it | Computed from | Used when |
|---|---|---|---|---|
| **Reach** | How many different people hit this? | One loud customer sends 20 messages about a typo; 12 customers each mention a failing export once. Counting messages would rank the typo first. Counting people ranks the export first. | Distinct customers; else distinct named speakers; else distinct sources | Always |
| **Revenue at risk** | How much money sits behind it? | Two problems each reported by 5 customers: one by trial users, one by accounts paying $50k a year. Reach cannot tell them apart; revenue can. | Sum of each affected customer's ARR, once per customer | Only when ARR is in the data |
| **Churn urgency** | Are people threatening to leave? | Frustration that ends in "we'll cancel" costs more to ignore than frustration that ends in "please fix". | Share of reporters whose messages contain churn language | Always |
| **Source spread** | Do independent channels agree? | A theme in call notes only may be one notetaker's emphasis. The same theme in calls, tickets and chat is hard to dismiss. | Number of distinct sources mentioning the theme | Project has 2+ sources |
| **Momentum** | Is it getting worse? | Two themes with equal totals: one doubled this fortnight, one faded. The first needs attention sooner. | Mentions in the last 14 days vs the 14 before, from real event dates | Enough feedback carries event dates |
| **Strategic accounts** | Does it reach the accounts the business depends on? | The same bug among trial users and among enterprise customers is not the same priority. | Share of reporting customers on the enterprise tier | Customer tiers are in the data |

Every theme shows the evidence for each signal: the customers and their ARR, the quotes with churn language, the
sources, the two momentum counts. Open the row and the proof is there.

## The formula

For a theme *t* in a project with *N* themes:

**1. Raw values, computed from stored data**

| Symbol | Signal | Raw value |
|---|---|---|
| R | Reach | r = number of distinct reporters (customers, else named speakers, else sources) |
| V | Revenue at risk | v = Σ over distinct customers c of ARR(c), each customer counted once at its largest ARR |
| U | Churn urgency | u = (reporters with churn language) ÷ r |
| S | Source spread | s = number of distinct sources |
| M | Momentum | m = (a − b) ÷ (a + b), where a = mentions in the last 14 days and b = mentions in the 14 days before; only when a + b ≥ 4 |
| E | Strategic accounts | e = (enterprise customers) ÷ (named customers) |

**2. Put every signal on the same 0-to-1 scale**

x̂ = (rank of x among the N themes − 1) ÷ (N − 1)

The lowest theme gets 0, the highest gets 1, and ties share their average rank (N = 1 gives 0.5). A theme with
none of something (x = 0, or a falling trend) gets x̂ = 0: no churn talk earns no churn points. This stops dollars
from outweighing counts just because the numbers are bigger.

**3. Weighted sum**

B2B SaaS (default):

Score = 100 × (0.25·R̂ + 0.30·V̂ + 0.20·Û + 0.10·Ŝ + 0.10·M̂ + 0.05·Ê)

Developer tools:

Score = 100 × (0.35·R̂ + 0.05·V̂ + 0.15·Û + 0.15·Ŝ + 0.25·M̂ + 0.05·Ê)

**4. Missing signals**

If a signal cannot be computed for the project, it is removed and the remaining weights are divided by their sum so
they still add up to 1: w′ₖ = wₖ ÷ Σⱼ wⱼ over the signals that remain.

**Worked example** (top theme in a test project with 3 themes):

Score = 100 × (0.25×1.00 + 0.30×1.00 + 0.20×1.00 + 0.10×0.50 + 0.10×1.00 + 0.05×1.00) = 95.0

The app shows this same line, with the theme's own numbers, under **Review & edit → The maths**.

## How the score is combined

1. Each signal's raw value is turned into a **percentile among the themes of the same project**, so no signal wins
   because its units are bigger (dollars against counts).
2. A signal that cannot be computed honestly for the project is **dropped, and its weight is shared among the rest**.
   The screen lists what was dropped and why ("No customer ARR in this project's data…").
3. `priority = 100 × Σ weight × percentile` over the signals that remain.

The weights are **product choices, not measured constants**, and they are shown with every score. Two presets exist:

| | Reach | Revenue | Urgency | Spread | Momentum | Strategic |
|---|---|---|---|---|---|---|
| **B2B SaaS** (default) | 25% | 30% | 20% | 10% | 10% | 5% |
| **Developer tools** | 35% | 5% | 15% | 15% | 25% | 5% |

Developer tools get their own preset because the people who report problems there are often not the people who sign
the contract, so reach and momentum carry more of the weight than revenue.

## Confidence

A theme is flagged **thin evidence** when it has fewer than 2 verified quotes or fewer than 3 mentions. The cohesion of
its cluster is shown next to it. This is a warning beside the score, not a weight inside it.

## Where the numbers come from

- **ARR and customer tier** exist only if the data carries them (an ARR column in a CSV or JSON export, a customer
  list). Where a file has a plan but no ARR, a default estimate per plan is used (enterprise $50k, growth $10k,
  starter $1k, free $0). Those are placeholders, not measured revenue. Documents, Slack and GitHub Issues carry no ARR,
  so for them revenue is dropped rather than shown as $0.
- **Event dates** come from the data itself: the seeded demo corpus stores them, connectors can carry them in
  `metadata.occurred_at`. Upload time is not an event date, so a project without carried dates drops momentum rather
  than guessing a trend.
- **Churn language** is detected in the message text with a fixed list of phrases.

## Known limits

- Reach counts named customers or speakers. Feedback with neither (a pasted document) counts per source, and the screen
  says "sources" instead of "customers".
- GitHub Issues and Slack do not carry event dates into the pipeline yet, so momentum is dropped for them.
- Severity ("is it a blocker?") and workaround friction need a model to judge the text. They are deliberately **not**
  in the score yet: when added, they will appear as labelled tags with the supporting quote, never as hidden weights.
- The weights have not been calibrated against real product decisions. Motif records every approve, edit and reject in
  the audit log, so the weights can later be fitted to what product managers actually approve.

## How to check it

- `tests/test_scoring.py` checks each signal against hand-computed values (repeat complaints count once, ARR counts once
  per account, ties, dropped signals, profile differences).
- `tests/test_scoring_db.py` runs the real pipeline against a real database and checks that the stored evidence matches
  the stored data and that the points add up to the score (`TEST_DB=1 pytest tests/test_scoring_db.py`).
