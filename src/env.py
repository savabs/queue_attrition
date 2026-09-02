"""Load .env for both manual and automated runs.

launchd starts jobs with a nearly empty environment: it does not read
~/.zshrc, ~/.zprofile or anything else. A key exported in a shell profile
therefore works perfectly when tested by hand and is absent every single night
in the scheduled job -- and the failure looks exactly like the source being
down, which is the worst kind of silent break.

So credentials live in .env, and every entrypoint loads them from there.
Existing environment variables win, so a one-off `PJM_API_KEY=... python ...`
still overrides the file.
"""
import os

_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")


def load(path: str = _ENV) -> list:
    """Set any variables defined in .env that are not already set. Returns the
    names it filled in, so callers can say what they picked up."""
    if not os.path.exists(path):
        return []
    filled = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if not val or os.environ.get(key):
                continue
            os.environ[key] = val
            filled.append(key)
    return filled
