# Live inbox

A customer message arrives (typed in the app, or sent by another tool) and the roadmap updates on screen: the message
joins the closest theme, the project is re-scored, and the page shows which numbers moved and why. No re-analysis, no
model call. Code: `app/core/live_inbox.py`, `app/core/rescore.py`, `app/api/v1/endpoints/inbox.py`;
screen: `triage-ui/src/components/LiveInbox.tsx` (beside the ranked list on the Roadmap tab).

## What happens to one message

1. **Read.** The text is cleaned the same way as uploaded feedback (markup and links removed) and kept word for word.
   Churn language is detected with the same phrase list as the pipeline.
2. **Embed.** The pipeline's own model, all-MiniLM-L6-v2, turns it into a 384-number vector.
3. **Match.** pgvector compares it with every message already in each theme of the latest analysis. The theme holding
   the most similar message wins, and only if that similarity (cosine, 0 to 1) reaches the threshold, **0.60**
   (`LIVE_MATCH_MIN_SIMILARITY`).
4. **Re-score.** The theme gets the message as another mention and another verified quote. Every theme in the
   analysis is scored again with the same arithmetic as the pipeline ([RANKING.md](RANKING.md)), so Reach, Revenue,
   Churn urgency, Source spread and Strategic accounts can change, and so can the kind-of-problem tag. A kind of problem
   set by a PM is kept.
5. **Explain.** The answer lists the theme, the similarity, the closest existing message, each theme's rank and score
   before and after, and the points each signal gained.

If nothing is similar enough, the message **waits**: it is stored and shown under "Recent messages", with how close it
came, and the next **Analyze** groups it with everything else (possibly into a new theme).

HDBSCAN is not re-run for one message. It groups all messages at once, so a single new message is matched to the
nearest theme instead, and the full regrouping happens on Analyze.

## Ways in

- **The app:** the Live feedback box. Editors and the owner can send; viewers can read the feed.
- **Webhook:** the project owner makes a secret link (Live feedback, "Send from other tools"). Anything that can send an
  HTTP request can post to it, with no sign-in: a Discord bot, a support desk's webhook, Zapier, `curl`. The link is
  shown once and only its SHA-256 fingerprint is stored; making a new link or turning it off stops the old one.
  At most 30 messages a minute per link, 64 KB per message.

Accepted bodies:

```json
{"text": "Export stops after 10,000 rows", "from": "Maya", "source": "discord", "customer": "Acme", "plan": "enterprise", "arr": 50000, "id": "msg-1", "occurred_at": "2026-10-01T09:30:00Z"}
```

a Discord message object (`content`, `author.username`, `id`, `timestamp`), or a support ticket
(`{"ticket": {"description", "requester", "id", "created_at"}}`). Only `text` is required. Sending the same `id` again
returns the first result instead of counting the message twice.

## What it does not do

- **Revenue is never guessed.** A message adds ARR only if the customer is already in this project's data (their
  recorded ARR is used, spelled as it is there) or the sender supplied `arr`. An unknown customer adds reach, urgency
  and spread, but no dollars.
- **Live messages carry no event date** unless the sender gives a real one (`occurred_at`, never in the future). When a
  message reached the inbox is not when it happened, so it does not feed Momentum.
- **A new problem does not appear instantly.** Four or more messages about something new are needed to form a theme, and
  that happens on Analyze.
- **It cannot read intent, only topic** (below).
- Messages sent while an analysis is running wait, so a re-analysis never races a live update.

## Where the 0.60 threshold comes from

Measured with the demo project (the eight files in `data/demo-sources`, analysed into 6 themes): 32 messages written
after the fact, none of them in the data. 22 are about one of the themes (including terse ones such as "export is
broken", "sso logs me out", "billing is wrong"); 10 are off-topic or about something else ("thanks for the quick reply!",
"I forgot my password", "we love the new dashboard layout").

| Threshold | On-topic messages that join | Off-topic messages that join |
|---|---|---|
| 0.50 | 21 of 22 | 5 of 10 |
| 0.55 | 20 of 22 | 1 of 10 |
| **0.60** | **19 of 22** | **0 of 10** |

The highest off-topic score was 0.56 (a compliment about the dashboard layout against the "dashboards are slow" theme);
the three on-topic messages that waited at 0.60 scored 0.58, 0.54 and 0.33 ("keep getting logged out", "login session too
short", "I have to log in again and again"). So the threshold errs on the side of waiting: a waiting message is
explained and grouped on the next Analyze, while a wrong join changes a ranking.

This is a small test on one project, not a benchmark. Similarity measures how close two messages are in topic. It cannot
tell a complaint from a compliment or a question about the same feature, so a message that is about export but is not a
problem can still join the export theme. The threshold is a setting (`LIVE_MATCH_MIN_SIMILARITY`, 0 to 1) so it can be
tuned on your own data: lower it to join more, raise it to join fewer.

## How to check it

- `tests/test_live_inbox.py` (needs `TEST_DB=1` for the database part): message parsing, the webhook link lifecycle
  (only a hash stored, replace, turn off, rate limit, repeated ids), roles (viewers cannot send, outsiders see nothing),
  a similar message joining its theme and overtaking another (rank, score and points checked against the stored data),
  unknown customers adding no revenue, a PM-set kind of problem surviving a live message, three messages sent at the
  same moment all being counted, and a re-score of the stored data equalling what the pipeline stored.
- By hand: Analyze the demo project, type "Slack alerts show up hours late" with customer "Halcyon Bank", and watch the
  Slack theme climb.
