"""Print a new VAPID key pair for Web Push as environment variables.

uv run python scripts/gen_vapid.py                     # print IHSP_PUSH__* lines
uv run python scripts/gen_vapid.py --out FILE          # write FILE (600) if missing
uv run python scripts/gen_vapid.py --out FILE --force  # replace an existing FILE

scripts/dev.sh uses `--out materials/dev-keys/vapid.env`, a git-ignored file.

The private key is a secret: keep it in the environment or a secret store and never
commit it. Replacing the pair signs every browser out of push (people have to switch
it on again), so `--out` keeps an existing file unless `--force` is given.
"""

import argparse
import sys
from pathlib import Path

from app.modules.notify.infrastructure.vapid import generate_vapid_keys


def render() -> str:
    """A fresh key pair as `.env` lines."""
    keys = generate_vapid_keys()
    return (
        "IHSP_PUSH__ENABLED=true\n"
        f"IHSP_PUSH__VAPID_PUBLIC_KEY={keys.public_key}\n"
        f"IHSP_PUSH__VAPID_PRIVATE_KEY={keys.private_key}\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Print the keys, or write them to `--out`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="write the lines to this file")
    parser.add_argument("--force", action="store_true", help="overwrite --out")
    args = parser.parse_args(argv)
    if args.out is None:
        sys.stdout.write(render())
        return 0
    if args.out.exists() and not args.force:
        return 0  # keep the pair browsers already subscribed with
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(), encoding="utf-8")
    args.out.chmod(0o600)
    sys.stderr.write(f"wrote {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
