"""Write docs/reference/settings.md from the field docs of app/settings.py.

    cd backend && uv run python scripts/settings_reference.py

A test fails while the file is out of date, so run this after changing a setting.
"""

from app.shared.settings_reference import write


def main() -> None:
    """Regenerate the settings reference."""
    print(f"wrote {write()}")


if __name__ == "__main__":
    main()
