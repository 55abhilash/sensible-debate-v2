# Sensible Debate

A place to argue slowly. Two strangers agree to talk about one topic. Each
person gets five minutes to write a full argument, then both sides get two
minutes of enforced quiet to actually read it before responding. No
interrupting, no pile-ons — one voice, then the other.

This is the v1 build: posting/joining topics, matching two strangers, and
the timed back-and-forth debate room itself. It's deployable either as a
single server (`DEPLOYMENT.md`) or across multiple autoscaling servers
on AWS (`DEPLOYMENT_AWS.md`) - the app code is the same either way; what
changes is how many copies of it run at once.

---

## How it works, end to end

1. Someone opens a topic ("Should remote work be the default?") and waits.
2. Someone else browses open topics and joins one. The two are now paired
   into a debate.
3. Both browsers connect to the debate room. The moment *both* are
   connected, the clock starts.
4. The topic's opener gets 5 minutes to write and send an argument.
5. Both people then get 2 minutes where nobody can send anything — just
   read and think.
6. The other person gets 5 minutes to respond. Then another 2-minute
   pause. Then back to the first person, and so on, indefinitely, until
   either person clicks **Leave**.
7. If someone lets their 5 minutes run out without sending anything, the
   server automatically records "No response was submitted in time" and
   moves the debate on — nobody can stall the other person forever.

There are no accounts. Each browser generates a random anonymous id and a
friendly generated name (e.g. "Thoughtful Heron") the first time it's
used, stored in `localStorage`. That's deliberate — the point is talking
to a stranger about an idea, not building a profile.

## Project layout

```
sensible-debate/
├── app/
│   ├── main.py            # FastAPI app: mounts static files, wires up the routers, /healthz
│   ├── config.py          # All tunable settings, overridable by environment variables
│   ├── database.py        # SQLAlchemy engine/session setup
│   ├── models.py          # Topic, DebateSession, DebateMessage - what gets persisted
│   ├── schemas.py         # Pydantic request/response shapes for the JSON API
│   ├── identity.py        # Generates friendly anonymous names ("Thoughtful Heron")
│   ├── realtime.py        # Redis coordination: shared state, pub/sub, distributed timers
│   ├── matchmaking.py     # Post/list/join/cancel topics; notifies a waiting browser
│   │                      #   the instant someone joins its topic (via realtime.py)
│   ├── debate_room.py     # The actual turn-by-turn logic, backed by realtime.py
│   ├── routes/
│   │   ├── pages.py       # Renders the three HTML pages (Jinja2)
│   │   ├── topics.py      # REST API: POST/GET/join/cancel topics
│   │   └── ws.py          # The two WebSocket endpoints (waiting room, debate room)
│   ├── templates/         # index.html, waiting.html, debate.html (+ base.html shell)
│   └── static/
│       ├── css/style.css  # The whole design system - see "Design notes" below
│       └── js/
│           ├── identity.js  # localStorage-based anonymous id/name + small helpers
│           ├── home.js      # Posting a topic, listing/joining open topics
│           ├── waiting.js   # The waiting-room websocket + cancel button
│           └── debate.js    # The debate room: timers, transcript, composer
├── tests/
│   └── end_to_end_check.py  # A scripted two-person debate over real websockets
├── terraform/               # AWS infrastructure - see DEPLOYMENT_AWS.md
├── Dockerfile                # Production container image (used by the AWS deployment)
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Only needed to run tests/end_to_end_check.py
├── run.py                  # Local dev entry point (`python run.py`)
├── .env.example             # Copy to .env to override any setting
├── .vscode/                 # Launch config + interpreter path, so it just opens and runs
├── DEPLOYMENT.md            # Step-by-step guide: one Ubuntu server
└── DEPLOYMENT_AWS.md        # Step-by-step guide: autoscaling on AWS
```

### The coordination layer: `app/realtime.py`

Debate state - whose turn it is, timers, the transcript so far - lives
in Redis as a small JSON blob per debate, not in a Python object. That's
what makes it safe to run this behind more than one process or server:
whichever process happens to be holding each person's actual WebSocket
connection reads and writes through Redis, and a Pub/Sub channel tells
every process the instant something changes, so it can push the update
to any local connections it's holding. `app/realtime.py` is genuinely
worth reading if you want to understand the mechanics - it's a fairly
short file, and the docstring at the top explains the three specific
problems it solves (shared state, cross-process notification, and
making sure a timer fires exactly once no matter how many processes are
watching for it).

### The turn-by-turn logic: `app/debate_room.py`

This is the one part of the app worth understanding properly if you
want to change the rules (e.g. the round limit, or what happens on
disconnect). Unlike an earlier version of this file, there's no
long-lived `Room` object anymore - every function reads the current
state from Redis, computes what should happen next, and writes it back:

- A debate stays in `"waiting"` phase until **both** browsers have an
  open WebSocket to it, on any process - this is what stops the clock
  from starting before the second person has actually arrived. A small
  Redis-based lock makes sure that if both connect at almost the exact
  same moment (quite possibly to two different processes), only one of
  them actually starts the clock.
- Each phase (`arguing`, `reflecting`) schedules its own deadline in
  Redis. An explicit submission or a fired timeout both first try to
  atomically "claim" that specific deadline (via an atomic Redis
  removal) - whichever wins actually processes it, and everything else
  backs off. This is what guarantees a 5-minute timer fires exactly
  once, even with several processes independently watching for expired
  ones.
- Every message that's actually sent (including auto-submitted ones) is
  written to the real database as it happens, so finished debates have
  a permanent transcript even though the live coordination state in
  Redis is only kept for a few hours (see "Known limitations").

A losing-a-connection is treated gently: if your browser tab drops the
websocket mid-debate (a refresh, a flaky connection, or even landing on
a *different* server on reconnect), the debate doesn't end - it just
marks you as disconnected, and reconnecting (anywhere) picks the debate
back up wherever it is. Only clicking **Leave** ends it.

## Design notes

The visual language is deliberately "letters, not a chat app" - a single
narrow reading column, hairline borders instead of card shadows, a serif
display face (Fraunces) for headings paired with a plain sans (IBM Plex
Sans) for body text and timers. Two colours carry real meaning inside the
debate room itself: moss green means "this is the reflection pause",
ochre means "it's your turn to write" - everywhere else the interface
stays quiet ink-on-paper on purpose, so those two moments actually stand
out when they matter.

## Running it locally

Redis is a required dependency now (it's how debate state is
coordinated - see above), even for a single local process:

```bash
# once, if you don't already have it:
sudo apt install redis-server    # macOS: brew install redis && brew services start redis

python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Then open `http://127.0.0.1:8000` in two different browsers (or one
normal window + one private/incognito window, since identity is stored
per-browser) to actually play both sides of a debate.

### Configuration

Every value in `app/config.py` can be overridden with an environment
variable - copy `.env.example` to `.env` and adjust, or export them
directly. The two you'll actually want to tweak:

| Variable                  | Default | What it controls                          |
|----------------------------|---------|--------------------------------------------|
| `SD_ARGUMENT_SECONDS`      | 300     | How long each turn to write lasts          |
| `SD_REFLECTION_SECONDS`    | 120     | How long the mandatory pause lasts         |
| `SD_MAX_ROUNDS`            | 0       | 0 = unlimited; otherwise auto-ends after N rounds each |
| `SD_TOPIC_EXPIRY_MINUTES`  | 60      | An unjoined topic is auto-closed after this |
| `SD_DATABASE_URL`          | sqlite  | Point at Postgres for a multi-instance deployment (see DEPLOYMENT_AWS.md) |
| `SD_REDIS_URL`             | `redis://127.0.0.1:6379/0` | Where live debate coordination happens |

### Testing

`tests/end_to_end_check.py` plays both sides of a full debate over real
websockets against a running server, and checks the turn order, the
timeout auto-submit, and that leaving ends it correctly for both people.
It's a good thing to run after changing anything in `debate_room.py`:

```bash
# terminal 1 - Redis running (see above), short timers so the test finishes in a few seconds
SD_ARGUMENT_SECONDS=3 SD_REFLECTION_SECONDS=2 python run.py

# terminal 2
pip install -r requirements-dev.txt
python tests/end_to_end_check.py
```

There's a second, more critical test worth knowing about even though
it isn't part of this repo's `tests/` directory: before building the
AWS deployment, two separate server processes (simulating two separate
instances) were run side by side, with the two debate participants
deliberately connected to *different* processes, to confirm the
cross-process coordination in `realtime.py` actually works - correct
start timing, message delivery, exactly-once timeout firing, and
correct ending, all across the process boundary. That's the specific
thing that would silently break if `realtime.py`'s coordination logic
ever regressed, so it's worth re-running by hand (start two `uvicorn`
processes on different ports against the same Redis and database, then
connect one participant to each) after touching anything in
`debate_room.py` or `realtime.py`.

## Known limitations (v1)

These are deliberate scope cuts, not oversights - worth knowing about
before you rely on this for real traffic:

- **A very small, low-probability race** between someone clicking
  "Leave" and a timeout firing for the same debate at almost exactly
  the same instant - documented in comments in `debate_room.py`. The
  realistic worst case is needing a page refresh, not data loss;
  deliberately not engineered away further given how rare and low-stakes
  it is.
- **Redis holds live debate state with a several-hour expiry, not
  forever.** If Redis loses an in-progress debate (a restart, an
  eviction), it resumes sensibly from the transcript already in the
  database rather than being lost outright - but this is a real trade-off,
  not a guarantee nothing is ever lost. Topics and every message already
  sent are always safe in the database regardless.
- **No accounts, no moderation, no reporting.** Anyone can open or join
  any topic. If you open this up publicly, you'll likely want at least a
  "report this" button and some basic rate limiting before wide release.
- **No spectators.** Only the two matched participants can see a debate.
- **A topic can only be joined by one other person.** There's no
  multi-person debate mode.

Reasonable next steps, roughly in order of value: a "report" button and
lightweight moderation queue, topic categories/tags so people can find
relevant debates, letting a finished debate be shared read-only via a
link, and (if traffic on AWS ever genuinely needs it) a WAF in front of
the load balancer - see DEPLOYMENT_AWS.md's own "Known limitations" for
deployment-specific trade-offs like single-AZ RDS.
