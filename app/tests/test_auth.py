"""V2.1 — accounts, project visibility, administration and the data notice."""

from __future__ import annotations

import os
import tempfile

import pytest

TMP = tempfile.mkdtemp(prefix="ner-auth-test-")
os.environ["NER_DATA_DIR"] = TMP
os.environ["NER_DATABASE_URL"] = f"sqlite:///{TMP}/test.sqlite3"

from fastapi.testclient import TestClient                       # noqa: E402

from app import auth as A                                       # noqa: E402
from app.db import SessionLocal, init_db                        # noqa: E402
from app.main import app                                        # noqa: E402


@pytest.fixture(scope="module")
def anon():
    init_db()
    return TestClient(app)


@pytest.fixture(scope="module")
def admin(anon):
    r = anon.post("/api/auth/bootstrap",
                  json={"username": "marcelo", "password": "a-long-test-phrase",
                        "display_name": "Marcelo"})
    assert r.status_code == 201, r.text
    return anon


@pytest.fixture(scope="module")
def member(admin):
    r = admin.post("/api/admin/users",
                   json={"username": "colleague", "password": "another-long-phrase",
                         "display_name": "Colleague", "is_admin": False})
    assert r.status_code == 201, r.text
    c = TestClient(app)
    r = c.post("/api/auth/login",
               json={"username": "colleague", "password": "another-long-phrase"})
    assert r.status_code == 200, r.text
    return c


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def test_a_password_is_never_stored_in_readable_form():
    stored = A.hash_password("a-long-test-phrase")
    assert "a-long-test-phrase" not in stored
    assert stored.startswith("scrypt$")
    assert A.verify_password("a-long-test-phrase", stored)
    assert not A.verify_password("a-long-test-phrasE", stored)
    assert not A.verify_password("", stored)


def test_two_identical_passwords_produce_different_hashes():
    """Salting: a stolen file must not reveal which accounts share a password."""
    assert A.hash_password("same-phrase-twice") != A.hash_password("same-phrase-twice")


def test_a_garbled_hash_is_a_failed_check_not_a_crash():
    for junk in ("", "nonsense", "scrypt$only$three", "bcrypt$1$2$3$ab$cd"):
        assert A.verify_password("anything", junk) is False


def test_the_policy_asks_for_length_not_theatre():
    A.check_password_policy("a long enough phrase")
    with pytest.raises(A.AuthError) as e:
        A.check_password_policy("Sh0rt!")
    assert "at least" in str(e.value)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_the_api_is_closed_before_anyone_signs_in(anon):
    fresh = TestClient(app)
    assert fresh.get("/api/projects").status_code == 401
    assert fresh.get("/api/meta").status_code == 401


def test_the_notice_and_the_state_are_readable_without_an_account(anon):
    fresh = TestClient(app)
    r = fresh.get("/api/auth/notice")
    assert r.status_code == 200
    body = r.json()
    assert body["statements"] and body["limits"]
    assert any("127.0.0.1" in s for s in body["statements"])
    # the notice has to say what is *not* protected, or it manufactures confidence
    assert any("no encryption at rest" in s.lower() for s in body["limits"])
    assert fresh.get("/api/auth/state").status_code == 200


def test_bootstrap_is_closed_once_an_account_exists(admin):
    r = admin.post("/api/auth/bootstrap",
                   json={"username": "intruder", "password": "a-long-test-phrase"})
    assert r.status_code == 422
    assert "already has accounts" in r.json()["detail"]


def test_a_wrong_username_and_a_wrong_password_look_the_same(admin):
    fresh = TestClient(app)
    a = fresh.post("/api/auth/login",
                   json={"username": "marcelo", "password": "wrong-but-long"})
    b = fresh.post("/api/auth/login",
                   json={"username": "nobody-here", "password": "wrong-but-long"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_signing_out_ends_the_session(admin):
    c = TestClient(app)
    c.post("/api/auth/login",
           json={"username": "marcelo", "password": "a-long-test-phrase"})
    assert c.get("/api/projects").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/projects").status_code == 401


def test_a_disabled_account_cannot_sign_in(admin):
    admin.post("/api/admin/users",
               json={"username": "temporary", "password": "a-long-test-phrase"})
    users = {u["username"]: u for u in admin.get("/api/admin/users").json()["users"]}
    uid = users["temporary"]["id"]

    c = TestClient(app)
    assert c.post("/api/auth/login",
                  json={"username": "temporary",
                        "password": "a-long-test-phrase"}).status_code == 200

    admin.post(f"/api/admin/users/{uid}/active", json={"value": False})
    r = TestClient(app).post("/api/auth/login",
                             json={"username": "temporary",
                                   "password": "a-long-test-phrase"})
    assert r.status_code == 401
    assert "disabled" in r.json()["detail"]
    # and the session they already held is gone
    assert c.get("/api/projects").status_code == 401


# ---------------------------------------------------------------------------
# Project visibility
# ---------------------------------------------------------------------------

def test_a_new_project_is_private_until_its_owner_says_otherwise(admin, member):
    pid = admin.post("/api/projects",
                     json={"name": "Private venue", "venue_code": "PRV"}).json()["id"]

    mine = admin.get("/api/projects").json()
    assert any(p["id"] == pid and p["visibility"] == "private" for p in mine)

    theirs = member.get("/api/projects").json()
    assert not any(p["id"] == pid for p in theirs), \
        "a private project must not appear for another account"
    # and it is indistinguishable from a project that does not exist
    assert member.get(f"/api/projects/{pid}").status_code == 404


def test_sharing_grants_reading_and_not_writing(admin, member):
    pid = admin.post("/api/projects",
                     json={"name": "Shared venue", "venue_code": "SHR"}).json()["id"]
    r = admin.post(f"/api/projects/{pid}/visibility", json={"visibility": "shared"})
    assert r.status_code == 200
    assert "outside this machine" in r.json()["note"]

    assert member.get(f"/api/projects/{pid}").status_code == 200
    row = [p for p in member.get("/api/projects").json() if p["id"] == pid][0]
    assert row["owner"] == "marcelo" and row["mine"] is False and row["can_edit"] is False

    r = member.patch(f"/api/projects/{pid}/settings", json={"general_limit_m": 80})
    assert r.status_code == 403
    assert "shared with you for reading" in r.json()["detail"]

    assert member.delete(f"/api/projects/{pid}").status_code == 403


def test_an_unknown_visibility_is_refused(admin):
    pid = admin.post("/api/projects", json={"name": "Vis venue"}).json()["id"]
    assert admin.post(f"/api/projects/{pid}/visibility",
                      json={"visibility": "public"}).status_code == 422


def test_an_admin_reaches_every_project(admin, member):
    pid = member.post("/api/projects",
                      json={"name": "Colleague venue", "venue_code": "COL"}).json()["id"]
    assert admin.get(f"/api/projects/{pid}").status_code == 200


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

def test_administration_is_closed_to_ordinary_accounts(member):
    assert member.get("/api/admin/users").status_code == 403
    assert member.post("/api/admin/users",
                       json={"username": "sneaky",
                             "password": "a-long-test-phrase"}).status_code == 403


def test_deleting_a_user_states_what_goes_with_them(admin):
    admin.post("/api/admin/users",
               json={"username": "leaver", "password": "a-long-test-phrase"})
    c = TestClient(app)
    c.post("/api/auth/login",
           json={"username": "leaver", "password": "a-long-test-phrase"})
    c.post("/api/projects", json={"name": "Leaver venue", "venue_code": "LVR"})

    uid = {u["username"]: u["id"]
           for u in admin.get("/api/admin/users").json()["users"]}["leaver"]

    impact = admin.get(f"/api/admin/users/{uid}/deletion-impact").json()
    assert impact["irreversible"] is True
    assert [p["name"] for p in impact["projects"]] == ["Leaver venue"]

    # a reason is required, and the username has to be typed out
    assert admin.post(f"/api/admin/users/{uid}/delete",
                      json={"reason": "", "confirm_username": "leaver"}).status_code == 422
    assert admin.post(f"/api/admin/users/{uid}/delete",
                      json={"reason": "left the programme",
                            "confirm_username": "wrong"}).status_code == 422

    r = admin.post(f"/api/admin/users/{uid}/delete",
                   json={"reason": "left the programme", "confirm_username": "leaver"})
    assert r.status_code == 200
    assert r.json()["projects_deleted"] == ["Leaver venue"]

    names = [p["name"] for p in admin.get("/api/projects").json()]
    assert "Leaver venue" not in names


def test_the_last_administrator_cannot_be_removed(admin):
    """An installation with no administrator cannot be recovered from inside."""
    uid = {u["username"]: u["id"]
           for u in admin.get("/api/admin/users").json()["users"]}["marcelo"]
    r = admin.post(f"/api/admin/users/{uid}/delete",
                   json={"reason": "testing", "confirm_username": "marcelo"})
    assert r.status_code == 422
    assert "own account" in r.json()["detail"]

    with SessionLocal() as db:
        from app.models import User
        only = db.get(User, uid)
        with pytest.raises(A.AuthError) as e:
            A.delete_user(db, only, reason="testing", actor="someone")
    assert "last active administrator" in str(e.value)


def test_an_admin_cannot_lock_themselves_out(admin):
    uid = {u["username"]: u["id"]
           for u in admin.get("/api/admin/users").json()["users"]}["marcelo"]
    assert admin.post(f"/api/admin/users/{uid}/active",
                      json={"value": False}).status_code == 422
    assert admin.post(f"/api/admin/users/{uid}/admin",
                      json={"value": False}).status_code == 422


def test_account_actions_reach_the_audit_log(admin):
    pid = admin.post("/api/projects", json={"name": "Audit venue"}).json()["id"]
    log = admin.get(f"/api/projects/{pid}/audit").json()
    assert any(e["actor"] == "marcelo" for e in log), \
        "the audit log must name the person, not “user”"
