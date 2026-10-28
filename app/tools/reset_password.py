"""Set a new password for an account that forgot it — on this computer.

    reset-password.bat                      (Windows, in the installation folder)
    mac/reset-password.command              (macOS)
    python tools/reset_password.py [username]

Lists the accounts of this installation, asks which one, asks for the new
password twice (nothing is shown while typing), and saves it. The account is
enabled again if it was disabled, every open session of it is signed out, and
the act is written to the account events. Works with the app running.

Why a program on the computer and not a "forgot password" link: the app has no
e-mail and runs only on this machine (127.0.0.1). Whoever can run a program in
this folder can already copy the database, so this opens no new door — it only
gives the owner of the computer a way back in without another administrator.
A colleague who forgot the password can also ask an administrator to use
"Reset password" on the Account & security screen.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _accounts(db) -> list:
    from sqlalchemy import select

    from app.models import User
    return list(db.execute(select(User).order_by(User.username)).scalars())


def main(argv: list[str]) -> int:
    os.chdir(ROOT)
    from app import auth as A
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        users = _accounts(db)
        if not users:
            print("This installation has no accounts yet. Open the app in the browser: "
                  "the first account is created on the sign-in screen.")
            return 1
        print("Accounts on this computer:")
        for u in users:
            flags = [f for f, on in (("administrator", u.is_admin),
                                     ("disabled", not u.is_active)) if on]
            print(f"  {u.username:<24} {u.display_name or ''}"
                  + (f"  ({', '.join(flags)})" if flags else ""))
        username = (argv[0] if argv else input("\nUsername to reset: ")).strip().lower()
        if not any(u.username == username for u in users):
            print(f"No account '{username}' on this computer. Nothing changed.")
            return 1
        print(f"\nNew password for '{username}' — at least {A.MIN_PASSWORD} characters. "
              "Nothing is shown while you type.")
        for _ in range(3):
            first = getpass.getpass("New password: ")
            second = getpass.getpass("Same password again: ")
            if first != second:
                print("The two passwords do not match — try again.")
                continue
            try:
                A.reset_on_this_computer(db, username, first)
            except A.AuthError as exc:
                print(f"Not saved: {exc}")
                continue
            print(f"\nDone. '{username}' can sign in with the new password "
                  "(open sessions of this account were signed out).")
            return 0
        print("Nothing changed.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
