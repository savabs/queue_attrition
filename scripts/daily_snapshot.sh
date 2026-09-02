#!/bin/zsh
# Daily snapshot of every ISO queue. Run by launchd; safe to run by hand.
#
# The whole thesis rests on this executing. The ISOs overwrite state in place,
# so a day this does not run is a day of revision history that cannot be
# recovered afterwards by anyone, including the ISO. It therefore fails loudly
# into the log rather than exiting quietly, and it never blocks on anything.

set -u
PROJECT="/Users/becmachlean/Projects/queue_attrition"
PY="$PROJECT/venv/bin/python"
LOG="$PROJECT/data/snapshots/run.log"

mkdir -p "$(dirname "$LOG")"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
print -r -- "===== $STAMP =====" >> "$LOG"

cd "$PROJECT" || { print -r -- "FATAL: no $PROJECT" >> "$LOG"; exit 1; }

# launchd hands this script an almost empty environment, so credentials come
# from .env rather than from any shell profile. src/env.py loads the same file
# on the Python side; this is here so anything shell-level sees it too.
if [[ -f "$PROJECT/.env" ]]; then
  set -a
  source "$PROJECT/.env"
  set +a
fi

if [[ ! -x "$PY" ]]; then
  print -r -- "FATAL: venv python missing at $PY" >> "$LOG"
  exit 1
fi

"$PY" src/snapshot.py >> "$LOG" 2>&1
RC=$?
print -r -- "snapshot.py exit=$RC" >> "$LOG"

# Commit only the archive. Scoping the add means an automated job can never
# sweep up half-finished source edits, and the git timestamp is what makes an
# entry un-backdatable later.
if [[ -n "$(git status --porcelain data/snapshots 2>/dev/null)" ]]; then
  git add data/snapshots
  git -c user.name="savabs" -c user.email="999.sbpatel@gmail.com" \
      commit -q -m "snapshot: $(date -u +%Y-%m-%d)" >> "$LOG" 2>&1
  print -r -- "committed $(git rev-parse --short HEAD)" >> "$LOG"
else
  print -r -- "nothing new to commit" >> "$LOG"
fi

# Surface staleness in the log. A job that silently stops is the only failure
# here that cannot be repaired afterwards, so it gets said out loud every run.
"$PY" src/health.py >> "$LOG" 2>&1
HRC=$?
if [[ $HRC -ne 0 ]]; then
  print -r -- "WARNING: archive health check returned $HRC — history is being lost" >> "$LOG"
fi

# Weekly nudge for a credential that is still missing. Mondays only, so it is
# not nagging, and it stops on its own the moment .env has the key -- no state
# file, nothing to remember to switch off.
if [[ "$(date +%u)" == "1" && -z "${PJM_API_KEY:-}" ]]; then
  /usr/bin/osascript -e 'display notification "PJM is the largest datacenter market publishing a queue. See NEXT.md." with title "queue_attrition" subtitle "PJM API key still missing"' 2>>"$LOG"
  print -r -- "nudge: PJM_API_KEY still unset" >> "$LOG"
fi

exit $RC
