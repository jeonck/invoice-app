"""Print a secrets.toml entry for a password. Run: python tools/hash_password.py

The password is read without echo and never written anywhere — only the
resulting hash is printed, for pasting into .streamlit/secrets.toml.
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import hash_password  # noqa: E402


def main() -> int:
    username = input("Username: ").strip()
    if not username:
        print("Username must not be empty.", file=sys.stderr)
        return 1

    password = getpass.getpass("Password: ")
    if len(password) < 12:
        print("Use at least 12 characters — this is the only thing standing "
              "between the internet and your invoices.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Password (again): "):
        print("The two passwords do not match.", file=sys.stderr)
        return 1

    print("\nAdd this to .streamlit/secrets.toml "
          "(or to Settings -> Secrets on Streamlit Cloud):\n")
    print("[app_auth.users]")
    print(f'{username} = "{hash_password(password)}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
