"""Sign-in, accounts, and the data-handling notice.

The notice deserves a word. It states **what the application does**, not what
policy it complies with — every line is something the reader can verify from
outside the app (``netstat`` for the bind address, the file system for the
database path). A blanket claim of compliance is exactly the sentence that fails
on contact with an auditor, and it would also be a claim this software has no
way to substantiate: it does not know the organisation's policy.

It includes what is *not* protected, for the same reason. A notice that implies
protection which is not there is worse than no notice, because it manufactures
confidence.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth as A
from ..config import settings
from ..db import get_session
from ..models import AuditLog, Project, User, UserSession, Visibility
from ..version import COPYRIGHT

router = APIRouter()


def _err(exc: A.AuthError) -> HTTPException:
    return HTTPException(422, str(exc))


# ---------------------------------------------------------------------------
# The dependencies every other router hangs off
# ---------------------------------------------------------------------------

def current_user(ner_session: Optional[str] = Cookie(default=None),
                 db: Session = Depends(get_session)) -> User:
    user = A.resolve_session(db, ner_session)
    if user is None:
        raise HTTPException(401, "sign in to continue")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "this needs an administrator account")
    return user


def project_guard(request: Request, user: User = Depends(current_user),
                  db: Session = Depends(get_session)) -> None:
    """Access control for every route with a ``project_id`` in its path.

    Applied once where the routers are included rather than repeated in a
    hundred handlers — a permission check that has to be remembered per endpoint
    is a permission check that will eventually be forgotten.

    Reading a shared project is allowed; writing to one is not. There is no
    concurrency control anywhere in this application, so two people confirming
    different matches on the same register would silently overwrite each other.
    Until that is solved, write access stays with the owner.
    """
    raw = request.path_params.get("project_id")
    if raw is None:
        return
    try:
        project_id = int(raw)
    except (TypeError, ValueError):
        return
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if not A.can_read_project(user, project):
        # Same answer as a missing project: whether a private project exists is
        # not something another account needs to learn.
        raise HTTPException(404, "project not found")
    # Taking a copy (4.6.0) only reads: a project shared for reading can be
    # exported by whoever can read it — the "take your own copy" below.
    if request.method == "POST" and request.url.path.rstrip("/").endswith(
            f"/projects/{project_id}/export"):
        return
    if request.method not in ("GET", "HEAD", "OPTIONS") and \
            not A.can_write_project(user, project):
        raise HTTPException(403, "this project is shared with you for reading. "
                                 "Ask its owner to make the change, or take your "
                                 "own copy.")


# ---------------------------------------------------------------------------
# The notice
# ---------------------------------------------------------------------------

def data_notice() -> dict:
    db_path = settings.database_url.replace("sqlite:///", "")
    return {
        "headline": "Where this data lives",
        "statements": [
            f"The application listens on 127.0.0.1 only. It opens no port on "
            f"any network, so nothing on the network can reach it.",
            "It makes no outbound connections. No project data is sent anywhere, "
            "to any external service, at any time.",
            f"Everything is stored in one file on this machine: {db_path}",
            f"Uploaded drawings and workbooks are kept as they were uploaded, "
            f"under {settings.data_dir}\\uploads.",
            "Every change is written to an audit log with the account that made "
            "it, the time and the justification given.",
            "Sign-in passwords are stored as scrypt hashes, never as text.",
        ],
        "limits": [
            "There is no encryption at rest. The database file is protected "
            "exactly as far as this machine's disk and account are — anyone with "
            "access to the computer's file system can read it.",
            "Sharing a project makes it readable by other accounts on this same "
            "installation. It does not publish it anywhere.",
            "Deleting a user deletes the projects they own, permanently.",
        ],
        "release": "Sharing project data outside this machine is a manual act by "
                   "a person exporting a file. The application never does it, and "
                   "any such release should follow your organisation's formal "
                   "approval and cybersecurity process.",
    }


@router.get("/auth/notice")
def notice() -> dict:
    """Readable without signing in — it is what the login screen shows."""
    return data_notice()


@router.get("/auth/state")
def state(ner_session: Optional[str] = Cookie(default=None),
          db: Session = Depends(get_session)) -> dict:
    """Who is signed in, or whether this installation still needs its first account."""
    user = A.resolve_session(db, ner_session)
    return {
        "authenticated": user is not None,
        "user": A.user_dict(user) if user else None,
        "needs_bootstrap": A.needs_bootstrap(db),
        "notice": data_notice(),
        "disclaimer": settings.disclaimer,
        # The version is public on purpose: the sign-in screen shows it, and
        # a browser holding an older bundle compares its own against this one
        # to say "reload" instead of quietly running last week's interface.
        "app": settings.app_name,
        "version": settings.version,
        "copyright": COPYRIGHT,
    }


# ---------------------------------------------------------------------------
# Sign in and out
# ---------------------------------------------------------------------------

class Credentials(BaseModel):
    username: str
    password: str


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        A.SESSION_COOKIE, token,
        max_age=A.SESSION_HOURS * 3600,
        httponly=True,
        samesite="lax",
        # The server is http on loopback, so a Secure cookie would never be sent.
        # Turning this on is part of putting the app behind TLS, not a default.
        secure=False,
        path="/",
    )


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response,
          db: Session = Depends(get_session)) -> dict:
    try:
        user, session = A.login(db, body.username, body.password,
                                user_agent=request.headers.get("user-agent", ""))
    except A.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    _set_cookie(response, session.token)
    A.purge_expired(db)
    return {"user": A.user_dict(user)}


class BootstrapIn(BaseModel):
    username: str
    password: str
    display_name: str = ""


@router.post("/auth/bootstrap", status_code=201)
def bootstrap(body: BootstrapIn, response: Response, request: Request,
              db: Session = Depends(get_session)) -> dict:
    """Create the first administrator. Refused once any account exists."""
    try:
        user = A.bootstrap_admin(db, username=body.username, password=body.password,
                                 display_name=body.display_name)
        _u, session = A.login(db, user.username, body.password,
                              user_agent=request.headers.get("user-agent", ""))
    except A.AuthError as exc:
        raise _err(exc) from exc
    _set_cookie(response, session.token)
    return {"user": A.user_dict(user)}


@router.post("/auth/logout")
def logout(response: Response, ner_session: Optional[str] = Cookie(default=None),
           db: Session = Depends(get_session)) -> dict:
    A.end_session(db, ner_session)
    response.delete_cookie(A.SESSION_COOKIE, path="/")
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/password")
def change_password(body: PasswordChange, user: User = Depends(current_user),
                    db: Session = Depends(get_session)) -> dict:
    if not A.verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "the current password is not right")
    try:
        A.set_password(db, user, body.new_password, actor=user.username)
    except A.AuthError as exc:
        raise _err(exc) from exc
    return {"ok": True}


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

@router.get("/admin/users")
def list_users(admin: User = Depends(require_admin),
               db: Session = Depends(get_session)) -> dict:
    users = db.execute(select(User).order_by(User.username)).scalars().all()
    projects = db.execute(select(Project)).scalars().all()
    owned: dict[int, list[str]] = {}
    for p in projects:
        if p.owner_id is not None:
            owned.setdefault(p.owner_id, []).append(p.name)
    sessions = db.execute(select(UserSession)).scalars().all()
    active: dict[int, int] = {}
    for s in sessions:
        active[s.user_id] = active.get(s.user_id, 0) + 1
    return {"users": [{**A.user_dict(u),
                       "projects": sorted(owned.get(u.id, [])),
                       "active_sessions": active.get(u.id, 0)}
                      for u in users]}


@router.get("/admin/audit")
def account_audit(limit: int = 500, admin: User = Depends(require_admin),
                  db: Session = Depends(get_session)) -> list[dict]:
    """The account events: sign-ins, accounts created, blocked, reset, deleted.

    They are written with no project, so the project audit log never showed
    them — a deletion "recorded in the audit log" that nobody could read
    (2.8.0 test pass). Administrators only: it names every account.
    """
    limit = max(1, min(int(limit), 5000))
    rows = db.execute(select(AuditLog).where(AuditLog.project_id.is_(None))
                      .order_by(AuditLog.at.desc(), AuditLog.id.desc())
                      .limit(limit)).scalars().all()
    return [{"at": a.at.isoformat(), "actor": a.actor, "action": a.action,
             "entity": a.entity, "entity_id": a.entity_id,
             "justification": a.justification, "payload": a.payload} for a in rows]


class NewUser(BaseModel):
    username: str
    password: str
    display_name: str = ""
    is_admin: bool = False
    must_change_password: bool = True


@router.post("/admin/users", status_code=201)
def create_user(body: NewUser, admin: User = Depends(require_admin),
                db: Session = Depends(get_session)) -> dict:
    try:
        user = A.create_user(db, username=body.username, password=body.password,
                             display_name=body.display_name, is_admin=body.is_admin,
                             actor=admin.username,
                             must_change_password=body.must_change_password)
    except A.AuthError as exc:
        raise _err(exc) from exc
    return A.user_dict(user)


def _target(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "user not found")
    return u


class FlagIn(BaseModel):
    value: bool


@router.post("/admin/users/{user_id}/active")
def set_active(user_id: int, body: FlagIn, admin: User = Depends(require_admin),
               db: Session = Depends(get_session)) -> dict:
    u = _target(db, user_id)
    if u.id == admin.id and not body.value:
        raise HTTPException(422, "you cannot disable your own account")
    return A.user_dict(A.set_active(db, u, body.value, actor=admin.username))


@router.post("/admin/users/{user_id}/admin")
def set_admin(user_id: int, body: FlagIn, admin: User = Depends(require_admin),
              db: Session = Depends(get_session)) -> dict:
    u = _target(db, user_id)
    if u.id == admin.id and not body.value:
        raise HTTPException(422, "you cannot remove your own administrator rights")
    return A.user_dict(A.set_admin(db, u, body.value, actor=admin.username))


class ResetIn(BaseModel):
    new_password: str


@router.post("/admin/users/{user_id}/password")
def reset_password(user_id: int, body: ResetIn, admin: User = Depends(require_admin),
                   db: Session = Depends(get_session)) -> dict:
    u = _target(db, user_id)
    try:
        A.set_password(db, u, body.new_password, actor=admin.username)
    except A.AuthError as exc:
        raise _err(exc) from exc
    u.must_change_password = True
    db.commit()
    return {"ok": True, "username": u.username}


@router.get("/admin/users/{user_id}/deletion-impact")
def deletion_impact(user_id: int, admin: User = Depends(require_admin),
                    db: Session = Depends(get_session)) -> dict:
    """What disappears with this account. Read this before confirming."""
    u = _target(db, user_id)
    projects = db.execute(select(Project).where(Project.owner_id == u.id)).scalars().all()
    return {
        "username": u.username,
        "projects": [{"id": p.id, "name": p.name, "venue_code": p.venue_code,
                      "drawings": len(p.drawings), "teap_files": len(p.teap_files),
                      "scenarios": len(p.scenarios)} for p in projects],
        "irreversible": True,
        "note": ("Deleting this account permanently deletes the projects listed "
                 "here, with their drawings, TEAP imports, NER registers, "
                 "snapshots and audit history. Export anything worth keeping "
                 "first."),
    }


class DeleteUserIn(BaseModel):
    reason: str
    confirm_username: str


@router.post("/admin/users/{user_id}/delete")
def delete_user(user_id: int, body: DeleteUserIn, admin: User = Depends(require_admin),
                db: Session = Depends(get_session)) -> dict:
    u = _target(db, user_id)
    if u.id == admin.id:
        raise HTTPException(422, "you cannot delete your own account")
    if body.confirm_username.strip().lower() != u.username:
        raise HTTPException(422, "type the username exactly to confirm — this "
                                 "deletes their projects too")
    try:
        return A.delete_user(db, u, reason=body.reason, actor=admin.username)
    except A.AuthError as exc:
        raise _err(exc) from exc
