"""Version of the clinical rules (LLD B4.7). Bump when flag, category, trend or status logic or its
configuration changes: rebuild_status --stale-only recomputes rows built with an older version."""
from typing import Final

RULES_VERSION: Final = "lab-rules-2"
