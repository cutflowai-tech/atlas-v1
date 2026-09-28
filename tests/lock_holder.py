"""Subprocess helper for lock tests: a separate process that holds or probes the real production lock.

    python lock_holder.py hold <operation> [target]   acquire, print the metadata, hold until stdin closes (or killed)
    python lock_holder.py probe                       try once without waiting; print {"acquired": bool, "holder": ...}

Configuration comes from the environment (ATLAS_DATA_DIR, ...), like the production commands.
"""

import json
import sys

from atlas_sync.config import load_sync_config
from atlas_sync.lock import OperationLocked, production_lock


def main() -> int:
    config = load_sync_config()
    if sys.argv[1] == "hold":
        with production_lock(config, sys.argv[2], target=sys.argv[3] if len(sys.argv) > 3 else None) as metadata:
            print(json.dumps(metadata), flush=True)
            sys.stdin.read()   # hold until the test closes stdin (or kills this process)
        return 0
    try:
        with production_lock(config, "run-once"):
            print(json.dumps({"acquired": True}), flush=True)
    except OperationLocked as locked:
        print(json.dumps({"acquired": False, **locked.as_dict()}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:   # Ctrl-C while holding: the with-block has already released the lock
        sys.exit(130)
