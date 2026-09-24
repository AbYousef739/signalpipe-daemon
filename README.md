# signalpipe-daemon

**The user-side sender for [SignalPipe](https://signalpipe.io) v4.**

> SignalPipe is the judgement layer for outreach. We never see your Reddit or X
> credentials and never see your LLM keys.
> **The math runs on us. The sending runs on you.**

This daemon holds a Server-Sent-Events stream open to your SignalPipe brain,
receives missions the brain has already scored, drafted, and approved, posts
them with **your own** platform credentials, and acknowledges the result. It
never sees your LLM keys, never scores or drafts anything itself, and keeps no
copy of your pipeline on this machine. It only sends. (Your leads and prospects
live in the managed brain, scoped to your account.)

## Install

```bash
pip install "signalpipe-daemon[all]"     # both Reddit + X senders
pip install "signalpipe-daemon[reddit]"  # Reddit only
pip install "signalpipe-daemon[twitter]" # X / Twitter only
pip install signalpipe-daemon            # base; pulls only `requests`
```

The platform SDKs (`praw`, `tweepy`) are optional extras and are imported only
when a mission for that channel actually arrives — install just the ones you use.

## Configure

Copy `.env.example` to `.env` and fill it in, or export the variables directly.
A real environment variable always wins over a `.env` entry.

| Variable | Purpose |
| --- | --- |
| `SIGNALPIPE_KEY` | **Required.** Your operator key from the dashboard. `SIGNALPIPE_OPERATOR_KEY` (the plugin's name for it) is accepted too. |
| `SIGNALPIPE_API_URL` | Brain URL. Defaults to `https://api.signalpipe.io`. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USERNAME` / `REDDIT_PASSWORD` | A Reddit *script* app on your sending account. Enables `reddit_comment` and `reddit_dm`. |
| `X_API_KEY` / `X_API_SECRET` / `X_ACCESS_TOKEN` / `X_ACCESS_SECRET` | X / Twitter app creds. Enables `twitter_reply`. |
| `MAX_TWITTER_ACTIONS_PER_DAY` | Default 10. |
| `MAX_REDDIT_DMS_PER_DAY` | Default 5. |
| `MAX_REDDIT_COMMENTS_PER_DAY` | Default 15. |

Your platform credentials stay on your machine. They are used only to talk to
Reddit / X directly and are **never** sent to SignalPipe.

**Reddit API access.** Since 11 November 2025 Reddit issues new API apps only
after a manual approval (its Responsible Builder Policy). If you do not already
have a script app, leave the `REDDIT_*` variables unset: approve drafts in your
agent, post them yourself, and mark them sent. **X** sending needs an X API
account on pay-per-use pricing (since February 2026), billed to you by X.

## Run

```bash
signalpipe-daemon status          # validate the key, print queue depth, exit
signalpipe-daemon run             # stream missions and send them
signalpipe-daemon run --dry-run   # log intended sends without posting or acking
```

`run` holds the stream open and reconnects with exponential backoff on any
network drop. A rejected key (401) is fatal and exits non-zero; everything else
is treated as transient. Stop with `Ctrl-C`.

## How a mission flows

1. The brain scores a signal, drafts a reply, and (once approved) marks the
   mission ready. It streams the mission to this daemon over SSE.
2. The daemon posts the pre-written draft on the mission's channel
   (`twitter_reply`, `reddit_comment`, or `reddit_dm`) using your credentials.
   Missions on the `manual` channel are skipped — you send those yourself.
3. The daemon acks the outcome. A failure tagged `banned` or `rate_limited`
   tells the brain to pause your stream for a cool-down.

**Daily caps** pace your sending; when a cap is hit the mission is *skipped*, not
failed, so it remains queued and retries after the next local-midnight reset.

**Delivery:** missions are delivered at-least-once. Within a running process the
daemon will never post the same mission twice, even across reconnects — so a
dropped connection is always safe to recover from.

## License

MIT — see [LICENSE](LICENSE).
