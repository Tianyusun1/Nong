import os
from pathlib import Path


def load_local_env(env_file='.env.local'):
    """Load KEY=VALUE pairs from a local env file if present."""
    path = Path(__file__).resolve().parent / env_file
    if not path.exists():
        return

    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
