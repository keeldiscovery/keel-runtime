# Amendment: a superseded agent session ends the runtime — without fighting for the account

**Amends**: [`spec.md`](spec.md) (the way out, `keel disconnect`) — its FR-010's neighbourhood
(`_say_goodbye`'s seam) and the assumption, until now unstated, that any non-2xx a runtime-
authenticated route can answer is either a `401` (re-authenticate) or an `ApiError` (fail the
call). A third case now exists, and this runtime's own last act — the goodbye — has to know to
skip itself when it does.

**Branch**: `superseded` | **Date**: 2026-09-09

**Input**: keel-cloud spec `035-one-runtime-per-founder`, in progress on its `master` at the time
of writing. That spec adds a **last-wins** rule: when a second runtime connects to the same
founder account, the older agent session is ended server-side and its running jobs requeued. The
superseded runtime learns of it on its next poll or job call — every runtime-authenticated route
(`/poll`, `/complete`, `/fail`) answers `410 Gone` with the connect envelope
`{"error":{"code":"AGENT_SESSION_SUPERSEDED","message":"another runtime connected to this account
and took over; this one is done — run keel connect here again to take it back"}}`. That repo is
the referee of this one and does not edit it; it states the requirement and the change is made
here.

*Spec kit is not used in this repository. This file is the record — there is no plan.md and no
tasks.md, and the work is one branch and one review.*

---

## What was wrong (or rather, what did not yet exist)

Before this change, `cloud_client.py` had exactly two outcomes for a non-2xx response: `401`
always raised `AuthenticationExpired`, and everything else raised `ApiError`. `poller.py` caught
`AuthenticationExpired` to re-authorize from scratch (clear the credential, run device
authorization again, create a fresh agent session) — the only response this runtime knew how to
recover from mid-poll.

A `410 AGENT_SESSION_SUPERSEDED` is not that. It does not mean the credential is bad — it means
the credential is *fine*, but this particular agent session is over because a **newer** runtime
already took the account. Treating it as a `401` would be actively wrong: `_reauthorize` would
mint a brand-new agent session, which itself would supersede the runtime that just took over,
which would then get superseded right back on its own next poll. Two runtimes chasing one
account in a loop, neither one ever settling into "the one connected" — exactly what "last-wins"
exists to prevent.

## What changed

**`keel_runtime/cloud_client.py`** — `_request` now recognises a `410` whose parsed body carries
`{"error": {"code": "AGENT_SESSION_SUPERSEDED", ...}}` and raises a new `AgentSessionSuperseded`
exception, carrying the server's own `message` verbatim (`exc.message`) — the sentence a founder
is meant to read. This check sits *after* the existing `401` check and *before* the general
`ApiError` construction, so a `410` carrying any other code — or no parseable code at all — is
unaffected and still raises `ApiError(410, code, message)` exactly as before this change.
`AgentSessionSuperseded` is deliberately its own exception class, not a subclass of
`AuthenticationExpired`: the two demand opposite responses, and a caller that used
`except AuthenticationExpired` broadly (there is only the one, in `poller.py`) must not
accidentally catch this one too.

**`keel_runtime/poller.py`** — `run_loop`'s per-cycle `try` gains an
`except AgentSessionSuperseded: raise` immediately above the existing
`except AuthenticationExpired`. It is a no-op in effect — nothing there could have caught it by
accident, since the two are unrelated exception types — but it is written down on purpose, as a
guard against a future `except Exception` landing above it unnoticed, and as the one place the
"this does not re-authorize" decision is stated next to the code it protects. The exception
propagates out of `run_loop` whole: no retry, no backoff, no heartbeat write, no re-authorization
attempt — `store.clear()`/`store.save()` are never called on this path (asserted directly in the
new test).

**`keel_runtime/cli.py`** — `_run_connect`'s outer `try` (the one that already wraps the
stored-credential reconnect, a fresh device authorization, and `run_loop`) gains
`except AgentSessionSuperseded as exc:`, ahead of the existing `except KeyboardInterrupt`. It
calls a new `_report_superseded(exc, config)` and returns `0` **immediately** — before the
`_say_goodbye` call below it is ever reached. `_report_superseded` does exactly two things:

1. Prints one line, in the same machine-readable `KEEL_*` signal-line family as `KEEL_USER_CODE=`
   and `KEEL_ENVIRONMENT=`: `KEEL_SUPERSEDED=1 message=<the server's own message>`.
2. Calls `heartbeat_module.remove(config.home)` directly — there is no `SIGTERM`/`SIGINT` here to
   let `_install_heartbeat_shutdown_handlers` do it for us, and a founder who runs `keel status`
   right after this must read `not_running`, not a stale record of a session the server has
   already ended.

The goodbye is skipped outright, not attempted-and-swallowed: the session this call would try to
end is already gone server-side, so `end_agent_session` would only earn a `404` — which
`_say_goodbye`'s own `except Exception` would swallow the same as any other failure (G1) — but
sending a doomed request for no reason is worse than not sending one, and skipping it here says so
directly rather than relying on G1 to paper over it.

The credential is **left exactly as it is** — `store.clear()` is never called on this path. That
is what lets a founder run `keel connect` here again: it creates a new agent session with the same
stored credential, which supersedes the runtime that took the account, taking it back.

## What is *not* changed

- The `401` path — `AuthenticationExpired` and `_reauthorize` — is untouched, and a dedicated test
  confirms a `401` still raises `AuthenticationExpired`, not `AgentSessionSuperseded`, even from
  the same fixture server that produces the 410.
- `ApiError`'s shape and every other non-2xx status. A `410` with a different code is still an
  `ApiError`, tested explicitly.
- `disconnect.py` and `keel disconnect` itself — untouched. This amendment is about the runtime
  *discovering* it has been disconnected from the far end, not about the local `disconnect`
  command, but it lands in this spec's directory because `003-keel-disconnect` is where the
  goodbye's seam (`_say_goodbye`, FR-010) and the heartbeat-removal vocabulary this amendment reuses
  were both designed.
- The goodbye call itself (`CloudClient.end_agent_session`) and its own tests
  (`tests/test_cloud_client_goodbye.py`) — unaffected; this amendment's runtime simply never
  reaches that call on the superseded path.
- No wire shape changes on this runtime's side beyond reading one more documented `410` code; no
  new dependency; the runtime stays standard-library-only.

## Behaviour, for the record

| Event | Before this change | After |
|---|---|---|
| `410` with code `AGENT_SESSION_SUPERSEDED`, anywhere | `ApiError(410, "AGENT_SESSION_SUPERSEDED", ...)`, uncaught in `poller.py` — the loop would crash | `AgentSessionSuperseded(message)`, caught in `cli.py`: one `KEEL_SUPERSEDED=1 message=...` line, heartbeat removed, goodbye skipped, credential kept, exit **0** |
| `410` with any other code | `ApiError` | unchanged — still `ApiError` |
| `401`, anywhere | `AuthenticationExpired`, re-authorizes from scratch | unchanged |
| `keel status`, right after a superseded exit | would have read the stale heartbeat (`running: true`) until it went stale | reads `not_running` immediately, same as after a clean `keel disconnect` |
| `keel connect`, run again after a superseded exit | n/a (the loop had crashed) | reuses the stored credential, creates a new agent session, supersedes the runtime that took over |

## Tests

`tests/test_agent_session_superseded.py` (new), against a real local `http.server` for the
wire-level and full-`connect` cases (in the style of `tests/test_cloud_client_goodbye.py` and
`tests/test_shutdown_goodbye.py`):

- `CloudClientSupersededTest` — a `410` with the code raises `AgentSessionSuperseded` carrying the
  server's message; a `410` with a different code still raises `ApiError`; a `401` from the same
  fixture still raises `AuthenticationExpired`.
- `RunLoopSupersededTest` — `run_loop` lets `AgentSessionSuperseded` propagate out untouched after
  a `NO_WORK` cycle (proving it isn't just "the first call"), with `store.clear`/`store.save`
  never called.
- `ConnectSupersededTest` — the whole `_run_connect` flow against a fake server whose first `poll`
  answers 410-superseded: exit code `0`, exactly one `KEEL_SUPERSEDED=1 message=...` line printed,
  the heartbeat file gone (`heartbeat.read` returns `None`), and the credential store's `clear`/
  `save` never called.

`python -m pytest` is green on 3.9 and 3.13: **371** now (366 before this amendment).
