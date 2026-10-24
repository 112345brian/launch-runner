# stackrun vs proclaunch: duplicate or upstream?

Written for the owner's decision on whether stackrun's single-instance claim belongs in proclaunch. Facts below come
from reading both code bases at `main` (proclaunch 0.2.0) plus branch `fix/register-self-atomic`; nothing here was
benchmarked, and the macOS/Linux behaviour of either library was not run (dev machine is Windows).

## Different jobs

| | stackrun | proclaunch |
|---|---|---|
| Lifetime | **Foreground**: the launcher process is the supervisor and lives as long as the stack | **Detached**: start a service, return, it outlives the caller |
| Unit | A `Stack` of N services, one launcher | One named service per record |
| Exit | Any service exits, or Ctrl+C / SIGHUP / SIGTERM: stop ALL, in reverse order, retry an interrupted stop once | `stop_service(name)`; no group semantics |
| Instances | Exactly one launcher per stack (claim file) | One live process per service name (reservation) |
| Extras | Port-clash check naming the holder, browser opener, `Hook`, `ready_url` gating | Readiness probes, Windows Task Scheduler / launchd supervisors, PTY spawner, windowless flags |

They do not compete as products. They overlap in one small layer: **"a record that names a process by identity, and
an atomic claim on it"**.

## Concrete overlap

| Concern | stackrun | proclaunch |
|---|---|---|
| Process identity | `Identity(pid, started)`, text `"pid started"`; rejects non-positive pid / nan / inf | `ProcessIdentity(pid, create_time)`, validated in `__post_init__` |
| Same-process check | `abs(create_time - started) < 1.0` and not a zombie | `abs(...) < 1e-3` and `proctree.alive` (so a zombie is not live) |
| Terminate tree | **Delegates** to `proclaunch.api.terminate_process` | Owns it |
| Claim | `FileRunRecord.claim`: `O_CREAT\|O_EXCL`, stale holder replaced, a just-created empty file is "held" for 5 s | `register_self(name)`: after the branch fix, `create_exclusive` or compare-and-swap `take_over` against the record just read, bounded retries |
| Release | `clear()` removes the file only if it names THIS process; `discard(identity)` only if it still names that identity | `RecordStore.delete_if(name, expected)` exists, but nothing public releases a self-registered record; `stop_service` kills the process |
| Stop another launcher | `Launcher.stop()`: kill recorded identity if alive, poll until gone (20 x 0.5 s), then discard; reports "did not stop in time" and keeps the record | `stop_service(name)`: identity-checked terminate, outcomes `STOPPED / ALREADY_STOPPED / PID_REUSED / UNCERTAIN` |
| Unreadable record | Garbage older than the grace period is treated as stale and replaced | `RecordUnreadable`: preserved and reported, **never** read as "stopped" |
| Race test | Six processes released by a go-file, exactly one `True` | Same shape, added on `fix/register-self-atomic` |

So stackrun's `FileRunRecord` is, today, a second implementation of `register_self` + `delete_if` + `stop_service`,
minus proclaunch's lock file and richer outcomes. The branch fix removes the reason (a check-then-act race) that made
stackrun's version better; the two are now equivalent on the race.

## Real differences that block a plain swap

1. **Unreadable/half-written records.** stackrun writes the identity into an `O_EXCL`-created file, so a reader can see
   an empty file; it handles that with a 5 s grace period. proclaunch writes through its atomic-file helper (I did not
   audit it), so that window may not exist, but its policy for a genuinely corrupt file is the opposite of
   stackrun's ("preserve and report" vs "replace after 60 s"). The owner should pick one policy.
2. **Release.** A foreground launcher must release its claim on exit. proclaunch has no `release_self`.
3. **Dependencies.** stackrun's default record needs only the stdlib plus a `Processes` port; proclaunch pulls
   `psutil`. Making the claim depend on proclaunch would give `stackrun` a hard dependency it currently keeps
   optional (`stackrun[proclaunch]` is only needed for tree-kill).
4. **Tolerance.** 1.0 s vs 1 ms for "same process". stackrun's value comes from the original launcher, where a
   record could be compared against a value rounded through text; proclaunch's stricter value is probably right for
   JSON floats. Unverified which is safer across platforms.

## Recommendation

Do not merge the products. Upstream **the claim**, in two steps, and keep stackrun's stdlib `FileRunRecord` until the
second step is proven:

1. In proclaunch, add `release_self(name)` (`delete_if` on the caller's own record) and decide the unreadable-record
   policy for self-registered records. Then `register_self` + `release_self` + `stop_service` cover everything
   `RunRecord` needs.
2. In stackrun, add `ProclaunchRunRecord` (a `RunRecord` adapter behind `stackrun[proclaunch]`) and run stackrun's
   own `check_run_record` conformance kit against it. If it passes, `FileRunRecord` can become a documented
   zero-dependency fallback or be dropped. The kit is the contract; nobody has to trust this note.

Until step 1 lands, duplication is small (about 60 lines) and tested on both sides by multi-process race tests, so
the cost of waiting is low. Duplicating long term is the worse option: the two would drift on exactly the
points in the table above (zombies, tolerance, unreadable files).
