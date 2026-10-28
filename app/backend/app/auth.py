"""Accounts, passwords and sessions.

What this protects, and what it does not
----------------------------------------
The server binds to ``127.0.0.1``. It opens no port on the network, and that is
the strongest security property this tool has — stronger than any password.
Accounts exist for two narrower reasons:

* the venue design data on a shared or unattended laptop should not be readable
  by whoever sits down at it;
* every decision in the audit log should name a real person instead of ``user``.

It is **not** multi-tenancy. Moving the app off loopback so that colleagues can
reach it is a different deployment with different obligations — TLS, an owner
for the machine, backups, patching, access review — and the notice this module
feeds to the interface says so plainly rather than implying protection that is
not there.

Why scrypt from the standard library
------------------------------------
``hashlib.scrypt`` is a memory-hard KDF and ships with Python, so the tool keeps
its "needs nothing but Python" property and there is no third-party crypto
dependency to track for advisories. The parameters below are the interactive
presets from the scrypt paper (N=2^15, r=8, p=1, ~32 MB per hash), which is
deliberately slow enough to make offline guessing expensive on a stolen laptop.

The stored form carries its own parameters, so raising them later does not
invalidate existing hashes — they are simply verified with the parameters they
were written under, and rewritten on the next successful login.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import re
import secrets
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, Project, User, UserSession, Visibility

#: interactive parameters — ~32 MB and a fraction of a second per hash
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

SESSION_HOURS = 12
SESSION_COOKIE = "ner_session"

USERNAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
MIN_PASSWORD = 10


class AuthError(ValueError):
    """A refused sign-in or account operation, with a sentence a user can act on."""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                         r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES,
                         maxmem=SCRYPT_N * SCRYPT_R * 200)
    return "$".join(["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
                     salt.hex(), key.hex()])


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a hash, using the parameters it was made with."""
    try:
        scheme, n, r, p, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(key_hex)
    except (ValueError, AttributeError):
        return False
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                               dklen=len(expected), maxmem=n * r * 200)
    return hmac.compare_digest(candidate, expected)


def check_password_policy(password: str) -> None:
    """Length first, because length is what actually resists guessing.

    No character-class rules: they push people toward ``Passw0rd!`` and buy very
    little. A long passphrase is both stronger and easier to type every morning.
    """
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"the password needs at least {MIN_PASSWORD} characters — "
                        "a short phrase you can remember beats a short scramble")
    if password.strip() != password:
        raise AuthError("the password cannot start or end with a space")


def check_username(username: str) -> str:
    u = (username or "").strip().lower()
    if not USERNAME_RX.match(u):
        raise AuthError("a username is 2–40 characters: lower case letters, "
                        "digits, dot, dash or underscore, starting with a letter "
                        "or digit")
    return u


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def user_count(db: Session) -> int:
    return len(db.execute(select(User.id)).scalars().all())


def needs_bootstrap(db: Session) -> bool:
    """True while no account exists — the only moment self-registration is open."""
    return user_count(db) == 0


def _audit(db: Session, actor: str, action: str, *, justification: str = "",
           payload: Optional[dict] = None, entity_id: Optional[int] = None) -> None:
    db.add(AuditLog(project_id=None, actor=actor, action=action, entity="user",
                    entity_id=entity_id, justification=justification,
                    payload=payload or {}))


def create_user(db: Session, *, username: str, password: str, display_name: str = "",
                is_admin: bool = False, actor: str = "system",
                must_change_password: bool = False) -> User:
    username = check_username(username)
    check_password_policy(password)
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise AuthError(f"the username “{username}” is already taken")
    user = User(username=username, display_name=display_name.strip() or username,
                password_hash=hash_password(password), is_admin=is_admin,
                created_by=actor, must_change_password=must_change_password)
    db.add(user)
    db.flush()
    _audit(db, actor, "user.created", entity_id=user.id,
           payload={"username": username, "is_admin": is_admin})
    db.commit()
    return user


def bootstrap_admin(db: Session, *, username: str, password: str,
                    display_name: str = "") -> User:
    """Create the first account. Refused once any account exists."""
    if not needs_bootstrap(db):
        raise AuthError("this installation already has accounts — ask an "
                        "administrator to create yours")
    user = create_user(db, username=username, password=password,
                       display_name=display_name, is_admin=True, actor="bootstrap")

    # Projects made before access control existed have no owner. Give them to the
    # first administrator rather than leaving them unreachable, and say so in the
    # log so it is never a mystery later.
    orphans = db.execute(select(Project).where(Project.owner_id.is_(None))).scalars().all()
    for p in orphans:
        p.owner_id = user.id
    if orphans:
        _audit(db, user.username, "user.adopted_projects", entity_id=user.id,
               justification="projects created before access control was enabled",
               payload={"projects": [p.name for p in orphans]})
    db.commit()
    return user


def set_password(db: Session, user: User, new_password: str, *,
                 actor: str = "user") -> User:
    check_password_policy(new_password)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    _audit(db, actor, "user.password_changed", entity_id=user.id,
           payload={"username": user.username})
    db.commit()
    return user


def reset_on_this_computer(db: Session, username: str, new_password: str) -> User:
    """The way back in for somebody who forgot the password (4.0.0).

    Run by ``reset-password.bat`` / ``mac/reset-password.command`` on the
    computer where the app is installed — never over the network, never from
    the browser. Whoever can run a program in the installation folder can
    already copy the whole database, so this opens no door that was not open;
    what it adds is a way back that does not need another administrator.

    Sets the new password, enables the account if it was disabled, signs out
    every open session of it, and writes the act to the account events as
    ``user.password_reset_on_this_computer``. The person chose the password
    themselves at the keyboard, so it is not flagged for a change on sign-in.
    """
    user = db.execute(select(User).where(User.username == (username or "").strip().lower())
                      ).scalar_one_or_none()
    if user is None:
        raise AuthError(f"no account “{username}” on this computer")
    check_password_policy(new_password)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    was_disabled = not user.is_active
    user.is_active = True
    end_all_sessions(db, user)
    _audit(db, "this computer", "user.password_reset_on_this_computer", entity_id=user.id,
           justification="forgotten password — reset with the reset-password tool on the "
                         "computer where the app is installed",
           payload={"username": user.username, "re_enabled": was_disabled})
    db.commit()
    return user


def set_active(db: Session, user: User, active: bool, *, actor: str) -> User:
    user.is_active = bool(active)
    if not active:
        end_all_sessions(db, user)
    _audit(db, actor, "user.enabled" if active else "user.disabled",
           entity_id=user.id, payload={"username": user.username})
    db.commit()
    return user


def set_admin(db: Session, user: User, is_admin: bool, *, actor: str) -> User:
    user.is_admin = bool(is_admin)
    _audit(db, actor, "user.admin_granted" if is_admin else "user.admin_revoked",
           entity_id=user.id, payload={"username": user.username})
    db.commit()
    return user


def delete_user(db: Session, user: User, *, reason: str, actor: str) -> dict:
    """Remove an account **and everything it owns**. Irreversible.

    Deliberately loud: it names every project that goes with it, refuses without
    a reason, and refuses to remove the last administrator — an installation with
    no administrator cannot be recovered from inside the application.
    """
    if not reason.strip():
        raise AuthError("deleting a user and their projects requires a reason")
    if user.is_admin:
        remaining = [u for u in db.execute(
            select(User).where(User.is_admin.is_(True), User.is_active.is_(True))
        ).scalars() if u.id != user.id]
        if not remaining:
            raise AuthError("this is the last active administrator — promote "
                            "someone else first, or the installation becomes "
                            "unmanageable")

    projects = db.execute(select(Project).where(Project.owner_id == user.id)).scalars().all()
    names = [p.name for p in projects]
    _audit(db, actor, "user.deleted", entity_id=user.id, justification=reason,
           payload={"username": user.username, "projects_deleted": names,
                    "project_count": len(names)})
    for p in projects:
        db.delete(p)
    db.delete(user)
    gone_ids = [p.id for p in projects]
    db.commit()
    # Their documents go with them (4.2.0), as the deletion card says.
    from .services import remove_project_files
    for pid in gone_ids:
        remove_project_files(pid)
    return {"username": user.username, "projects_deleted": names}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def login(db: Session, username: str, password: str, *, user_agent: str = ""
          ) -> tuple[User, UserSession]:
    u = (username or "").strip().lower()
    user = db.execute(select(User).where(User.username == u)).scalar_one_or_none()

    # One message for both failures, and the hash runs either way, so a wrong
    # username and a wrong password are indistinguishable in wording and timing.
    if user is None:
        hash_password(password or "x")
        raise AuthError("username or password is not right")
    if not verify_password(password or "", user.password_hash):
        raise AuthError("username or password is not right")
    if not user.is_active:
        raise AuthError("this account is disabled — ask an administrator")

    session = UserSession(
        token=secrets.token_urlsafe(48), user_id=user.id,
        expires_at=_now() + _dt.timedelta(hours=SESSION_HOURS),
        user_agent=(user_agent or "")[:300])
    db.add(session)
    user.last_login_at = _now()
    _audit(db, user.username, "user.signed_in", entity_id=user.id)
    db.commit()
    return user, session


def resolve_session(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    s = db.get(UserSession, token)
    if s is None:
        return None
    expires = s.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=_dt.timezone.utc)
    if expires < _now():
        db.delete(s)
        db.commit()
        return None
    user = db.get(User, s.user_id)
    if user is None or not user.is_active:
        return None
    return user


def end_session(db: Session, token: Optional[str]) -> None:
    if not token:
        return
    s = db.get(UserSession, token)
    if s is not None:
        db.delete(s)
        db.commit()


def end_all_sessions(db: Session, user: User) -> None:
    for s in db.execute(select(UserSession)
                        .where(UserSession.user_id == user.id)).scalars().all():
        db.delete(s)


def purge_expired(db: Session) -> int:
    gone = 0
    for s in db.execute(select(UserSession)).scalars().all():
        expires = s.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_dt.timezone.utc)
        if expires < _now():
            db.delete(s)
            gone += 1
    if gone:
        db.commit()
    return gone


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------

def can_read_project(user: User, project: Project) -> bool:
    return (user.is_admin
            or project.owner_id == user.id
            or project.owner_id is None
            or project.visibility == Visibility.SHARED)


def can_write_project(user: User, project: Project) -> bool:
    """Sharing is read-only on purpose.

    A shared project is something a colleague can look at, not something two
    people edit at once. This application has no concurrency control — two
    people confirming different matches on the same register would silently
    overwrite each other — so write access stays with the owner until that is
    solved properly.
    """
    return user.is_admin or project.owner_id == user.id or project.owner_id is None


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "is_admin": u.is_admin, "is_active": u.is_active,
            "must_change_password": u.must_change_password,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "created_by": u.created_by,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}
