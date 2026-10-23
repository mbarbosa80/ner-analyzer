"""4.0.0 — one set of numbers in every sheet, the TEAP as the only source of
ports, access points placed exactly as the DWISA line states, placing that
never duplicates, the tab order of 16 Oct 2026 and a way back in for a
forgotten password.

Marcelo, 16 Oct 2026, after another analysis found 576 vs 519 ports on a NER,
842 vs 839 requested and 13/8/2 vs 14/9 indoor/outdoor between the sheets of
the RIV workbook: *"O NER tem que bater em todas as planilhas."* And:
*"AP não é um produto do TEAP. Mantenha somente a informação que já existe
que é o produto DWISA … o número de AP placed nos desenhos deveria seguir
rigorosamente esta qtde, e para os lugares não encontrados no VDB, não fazer
nada, mantendo-os como pending - no NER. Clicar duas vezes no botão place AP
ou Place NER não pode duplicar o que já foi feito."*
"""

from __future__ import annotations

import datetime as _dt
import pathlib

import openpyxl
import pytest
from sqlalchemy import select

from tests.test_wireless_tie_250 import (DWISA, _analyse, _ap, _line, _match,  # noqa: F401
                                         _ner, _project, _room, _teap, client)
from app import auth as A
from app import services as S
from app.config import settings
from app.db import SessionLocal
from app.domain.reports import SHEET_ORDER
from app.models import AuditLog, Element, NerAsset, User, UserSession

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _workbook(client, pid):
    r = client.post(f"/api/projects/{pid}/reports/xlsx?background=false")
    assert r.status_code == 200, r.text
    return openpyxl.load_workbook(settings.exports_dir / f"project_{pid}" / r.json()["file"])


def _place(client, pid):
    r = client.post(f"/api/projects/{pid}/wireless/place-from-teap")
    assert r.status_code == 200, r.text
    return r.json()


def _points(pid, key=None):
    with SessionLocal() as db:
        q = select(Element).where(Element.project_id == pid, Element.kind == "WIRELESS")
        if key:
            q = q.where(Element.space_key == key)
        return list(db.execute(q.order_by(Element.id)).scalars())


def _set_env(pid, label, env, *, removed=False):
    with SessionLocal() as db:
        a = next(a for a in db.execute(select(NerAsset).where(
            NerAsset.project_id == pid)).scalars() if a.display_name == label)
        a.environment = env
        if removed:
            a.deleted_at = _dt.datetime.now(_dt.timezone.utc)
        db.commit()


# ---------------------------------------------------------------------------
# The same numbers in every sheet
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def riv(client):
    """A small RIV: two matched spaces with DWISA, one space not on the
    drawing (pending, with DWISA), access points placed from the TEAP, one
    drawn by hand and tied to nothing, three live NERs (indoor, outdoor, not
    said) and a removed one marked indoor — the shape of the real defect."""
    pid = _project("riv-400")
    _room(pid, "OFF.010", "Office", 100, 100)
    _room(pid, "MED.020", "Media", 500, 100)
    _teap(pid, "OFF.010", "Office", [_line("Laptop", 4, 4, "LAP", 1),
                                    _line(DWISA, 1, 1, "DWISA", 2)])
    _teap(pid, "MED.020", "Media", [_line("Printer", 1, 1, "PRN", 3),
                                   _line(DWISA, 2, 2, "DWISA", 4),
                                   _line("Monitor", 2, 0, "MON", 5)])
    _teap(pid, "GHO.099", "Nowhere", [_line("Laptop", 3, 3, "LAP", 6),
                                     _line(DWISA, 1, 1, "DWISA", 7)])
    _ner(pid, "NER_20.1", 100, 130)
    _ner(pid, "NER_21.1", 500, 130)
    _ner(pid, "NER_22.1", 900, 600)
    _ner(pid, "NER_23.1", 300, 300)
    _set_env(pid, "NER_20.1", "indoor")
    _set_env(pid, "NER_21.1", "outdoor")
    _set_env(pid, "NER_23.1", "indoor", removed=True)
    _match(client, pid)
    placed = _place(client, pid)
    _ap(client, pid, 900, 590)            # by hand, near no matched room: tied to nothing
    _analyse(pid)
    return pid, placed, _workbook(client, pid)


def _summary(wb):
    return {r[0]: r[1] for r in wb["Summary"].iter_rows(min_row=2, values_only=True)}


def _figures(wb):
    return {r[1]: r[2] for r in wb["Coverage figures"].iter_rows(min_row=2, values_only=True)}


def test_ports_requested_on_a_ner_and_pending_agree_on_every_sheet(riv):
    _, _, wb = riv
    s, f = _summary(wb), _figures(wb)
    teap = 4 + 1 + 1 + 2 + 0 + 3 + 1          # every TEAP port, DWISA included
    on_ner = 4 + 1 + 1 + 2
    pending = 3 + 1

    assert s["Totals: Total ports requested (TEAP)"] == teap
    assert f["ports requested by the study (TEAP)"] == teap
    assert sum(r[16] or 0 for r in wb["TEAP and coverage"].iter_rows(min_row=2, values_only=True)
               if r[0]) == teap

    assert s["Totals: Ports on a NER (assigned in this run)"] == on_ner
    assert f["ports on a NER"] == on_ner
    ners = [r for r in wb["NERs and ports"].iter_rows(min_row=2, values_only=True)
            if r[0] and r[0] != "TOTAL"]
    assert sum(r[7] for r in ners) == on_ner

    assert s["Totals: Ports on no NER yet (pending)"] == pending
    assert f["ports on no NER yet (pending)"] == pending
    assert s["  of which wireless (DWISA)"] == f["  of which wireless (DWISA)"] == 1 + 2 + 1

    # TEAP by NER: every TEAP line, nothing else; NER groups = Ports assigned
    rows = list(wb["TEAP by NER"].iter_rows(min_row=2, values_only=True))
    lines = [r for r in rows if isinstance(r[6], (int, float))]
    assert sum(r[6] for r in lines) == teap
    assert sum(r[6] for r in lines if r[0] != "Pending — no NER") == on_ner
    assert not any(r[4] == "AP" for r in lines), "an access point is not a TEAP product"
    assigned = {r[0]: r[7] for r in ners}
    for ner, total in assigned.items():
        assert sum(r[6] for r in lines if r[0] == ner) == total, ner


def test_indoor_outdoor_count_the_same_rooms_everywhere_and_never_a_removed_one(riv):
    _, _, wb = riv
    s, f = _summary(wb), _figures(wb)
    assert (s["Totals: NERs indoor"], s["Totals: NERs outdoor"],
            s["Totals: NERs indoor/outdoor not said"]) == (1, 1, 1)
    assert (f["    indoor"], f["    outdoor"], f["    indoor / outdoor not said"]) == (1, 1, 1)
    ws = wb["NERs and ports"]
    total = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] == "TOTAL")
    assert total[5] == "1 indoor / 1 outdoor / 1 not said"
    labels = [r[0] for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
    assert "NER_23.1" not in labels


def test_access_points_are_listed_with_no_port_column(riv):
    _, _, wb = riv
    ws = wb["Wireless points"]
    head = [c.value for c in ws[1]]
    assert "Ports" not in head and head[7] == "TEAP space"     # 4.5.0: + Indoor / outdoor
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True)]
    assert len(rows) == 1 + 1 + 1          # Office 1, Media 1 (one per space, 4.3.0), the hand-drawn one
    loose = [r for r in rows if not r[7]]
    assert len(loose) == 1 and "no port counted" in loose[0][9]


def test_tabs_come_in_the_order_of_the_screenshot_with_only_three_coloured(riv):
    _, _, wb = riv
    assert wb.sheetnames == [n for n in SHEET_ORDER if n in wb.sheetnames]
    assert wb.sheetnames[:4] == ["TEAP by NER", "NERs and ports", "Wireless points", "Summary"]
    assert SHEET_ORDER == ["TEAP by NER", "NERs and ports", "Wireless points", "Summary",
                           "TEAP and coverage", "Matching", "Match exceptions", "Exceptions",
                           "TEAP spaces with no ports", "Scales", "Coverage figures"]
    colour = {ws.title: (ws.sheet_properties.tabColor.rgb if ws.sheet_properties.tabColor
                         else None) for ws in wb.worksheets}
    assert colour.pop("TEAP by NER").endswith("FF0000")
    assert colour.pop("NERs and ports").endswith("FFFF00")
    assert colour.pop("Wireless points").endswith("FFFF00")
    assert set(colour.values()) == {None}
    # one tab selected, the first: never two grouped tabs
    assert [ws.title for ws in wb.worksheets if ws.sheet_view.tabSelected] == ["TEAP by NER"]
    assert wb.active.title == "TEAP by NER"


# ---------------------------------------------------------------------------
# Place APs from the TEAP: exactly the DWISA quantity, never twice
# ---------------------------------------------------------------------------

def test_one_wifi_point_per_space_with_dwisa_and_spaces_off_the_drawing_get_nothing(riv):
    """4.3.0: one Wi-Fi point per space with a DWISA line, whatever its
    quantity — Media asks for 2 and gets one point; the quantity stays on the
    DWISA line. Before 4.3.0 it got two."""
    pid, placed, _ = riv
    assert placed["placed"] == 2 and placed["spaces_placed"] == 2
    assert placed["no_room"] == 1 and placed["unplaced_spaces"] == ["Nowhere"]
    assert len(_points(pid, "TST|OFF.010")) == 1
    assert len(_points(pid, "TST|MED.020")) == 1
    assert _points(pid, "TST|GHO.099") == []


def test_pressing_place_aps_again_adds_nothing(client, riv):
    pid, _, _ = riv
    before = [e.id for e in _points(pid)]
    again = _place(client, pid)
    assert again["placed"] == 0 and again["removed_extra"] == 0
    assert again["already_had_points"] == 2
    assert [e.id for e in _points(pid)] == before


def test_extra_points_it_placed_are_taken_back_but_never_a_hand_drawn_one(client):
    pid = _project("ap-extra-400")
    _room(pid, "OFF.030", "Office", 100, 100)
    key = _teap(pid, "OFF.030", "Office", [_line(DWISA, 1, 1, "DWISA", 1)])
    _ner(pid, "NER_20.1", 100, 130)
    _match(client, pid)
    _place(client, pid)
    # a double run of an older version left three copies of the one AP
    with SessionLocal() as db:
        first = db.execute(select(Element).where(Element.project_id == pid,
                                                 Element.space_key == key)).scalars().one()
        for n in (2, 3):
            db.add(Element(project_id=pid, drawing_id=first.drawing_id, page=1,
                           kind="WIRELESS", label=f"WIFI-{n}", x=first.x, y=first.y,
                           origin="teap", tie_source="teap", space_key=key, confirmed=True,
                           confidence=1.0))
        db.commit()
    r = _place(client, pid)
    assert r["removed_extra"] == 2 and r["removed_names"] == ["WIFI-3", "WIFI-2"]
    assert [e.label for e in _points(pid, key)] == ["WIFI-1"]

    # a point drawn by hand and tied to the same space is never removed
    hand = _ap(client, pid, 104, 104)
    assert hand["space_key"] == key
    r = _place(client, pid)
    assert r["removed_extra"] == 1 and r["extra_by_hand"] == 0      # the TEAP one goes
    assert [e.label for e in _points(pid, key)] == [hand["label"]]
    r = _place(client, pid)
    assert r["removed_extra"] == 0 and r["placed"] == 0


def test_a_space_whose_dwisa_quantity_is_zero_gets_no_access_point(client):
    pid = _project("ap-zero-400")
    _room(pid, "OFF.040", "Office", 100, 100)
    _teap(pid, "OFF.040", "Office", [_line("Laptop", 1, 1, "LAP", 1),
                                    _line(DWISA, 0, 0, "DWISA", 2)])
    _ner(pid, "NER_20.1", 100, 130)
    _match(client, pid)
    r = _place(client, pid)
    assert r["placed"] == 0 and r["spaces_with_wireless"] == 0
    assert _points(pid) == []


def test_a_second_press_while_the_first_runs_is_refused(client):
    pid = _project("ap-busy-400")
    with S.one_at_a_time(pid, "aps", S.PLACE_APS_BUSY):
        r = client.post(f"/api/projects/{pid}/wireless/place-from-teap")
        assert r.status_code == 409 and r.json()["detail"] == S.PLACE_APS_BUSY
    with S.one_at_a_time(pid, "ners", S.PLACE_NERS_BUSY):
        r = client.post(f"/api/projects/{pid}/ners/place-from-drawing")
        assert r.status_code == 409 and r.json()["detail"] == S.PLACE_NERS_BUSY
    # released: the next press runs
    assert client.post(f"/api/projects/{pid}/wireless/place-from-teap").status_code == 200


def test_the_buttons_ignore_a_second_click_before_the_screen_updates():
    src = (ROOT / "frontend" / "src" / "pages" / "panels.tsx").read_text(encoding="utf-8")
    assert "placingNersRef.current" in src and "placingApsRef.current" in src
    assert "if (placingNersRef.current || placeJob.busy) return;" in src
    assert "if (placingApsRef.current) return;" in src


# ---------------------------------------------------------------------------
# Forgot the password
# ---------------------------------------------------------------------------

def test_the_reset_tool_sets_the_password_enables_and_signs_out(client):
    with SessionLocal() as db:
        u = A.create_user(db, username="forgetful", password="first-long-phrase",
                          actor="tests")
        u.is_active = False
        db.add(UserSession(token="t" * 43, user_id=u.id,
                           expires_at=_dt.datetime.now(_dt.timezone.utc)
                           + _dt.timedelta(hours=1)))
        db.commit()
        with pytest.raises(A.AuthError):
            A.reset_on_this_computer(db, "forgetful", "short")
        with pytest.raises(A.AuthError):
            A.reset_on_this_computer(db, "nobody-here", "a-long-new-phrase")
        A.reset_on_this_computer(db, "Forgetful", "a-long-new-phrase")
        u = db.execute(select(User).where(User.username == "forgetful")).scalar_one()
        assert u.is_active and not u.must_change_password
        assert A.verify_password("a-long-new-phrase", u.password_hash)
        assert not db.execute(select(UserSession).where(UserSession.user_id == u.id)).first()
        assert db.execute(select(AuditLog).where(
            AuditLog.action == "user.password_reset_on_this_computer")).first()


def test_the_reset_tool_runs_from_the_command_line(monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("reset_password",
                                                  ROOT / "tools" / "reset_password.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with SessionLocal() as db:
        A.create_user(db, username="cli-user", password="first-long-phrase", actor="tests")
    answers = iter(["typed-new-phrase", "typed-new-phrase"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert mod.main(["cli-user"]) == 0
    out = capsys.readouterr().out
    assert "cli-user" in out and "Done." in out
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == "cli-user")).scalar_one()
        assert A.verify_password("typed-new-phrase", u.password_hash)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "x")
    assert mod.main(["no-such-user"]) == 1


def test_the_reset_tool_ships_on_both_systems():
    bat = (ROOT / "reset-password.bat").read_bytes()
    assert b"\r\n" in bat and b"tools\\reset_password.py" in bat and b"PYTHONNOUSERSITE" in bat
    cmd = ROOT / "mac" / "reset-password.command"
    import os
    if os.name != "nt":            # Windows keeps no executable bit; the zip carries it
        assert cmd.stat().st_mode & 0o111
    assert "tools/reset_password.py" in cmd.read_text()
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_package", ROOT / "tools" / "make_package.py")
    mp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mp)
    assert "reset-password.bat" in mp.REQUIRED and "tools/reset_password.py" in mp.REQUIRED
    assert "mac/reset-password.command" in mp.REQUIRED_MAC
    assert "reset_password.py" in mp.SHIP_TOOLS


def test_the_sign_in_screen_says_how_to_get_back_in():
    src = (ROOT / "frontend" / "src" / "pages" / "Access.tsx").read_text(encoding="utf-8")
    assert 't("Forgot your password?")' in src
    assert "reset-password.bat" in src and "reset-password.command" in src
    pt = (ROOT / "frontend" / "src" / "lib" / "strings.pt.ts").read_text(encoding="utf-8")
    assert '"Forgot your password?":' in pt


def test_a_run_saved_before_400_is_counted_the_new_way_in_the_export(client):
    """A project analysed by 3.0.0 keeps its saved As-Is run until somebody
    presses Run analysis. Its stored ports were the old ones (an AP = 1 port,
    the DWISA line off the space); the export must still add up."""
    from app.models import Project, Scenario
    pid = _project("old-run-400")
    _room(pid, "OFF.050", "Office", 100, 100)
    _teap(pid, "OFF.050", "Office", [_line("Laptop", 4, 4, "LAP", 1),
                                    _line(DWISA, 1, 1, "DWISA", 2)])
    _ner(pid, "NER_20.1", 100, 130)
    _match(client, pid)
    _place(client, pid)
    _analyse(pid)
    with SessionLocal() as db:
        sc = db.execute(select(Scenario).where(Scenario.project_id == pid,
                                               Scenario.name == "As-Is")).scalar_one()
        payload = dict(sc.result)
        old = []
        for a in payload["assignments"]:
            a = dict(a)
            a["ports_required"] = 1.0 if a.get("kind") == "wireless_point" else 4.0
            old.append(a)
        payload["assignments"] = old
        payload["ner_load"] = {k: {**v, "assigned_ports": 5.0, "wireless_ports": 1.0}
                               for k, v in payload["ner_load"].items()}
        sc.result = payload
        db.commit()
    wb = _workbook(client, pid)
    s, f = _summary(wb), _figures(wb)
    assert s["Totals: Total ports requested (TEAP)"] == f["ports requested by the study (TEAP)"] == 5
    assert s["Totals: Ports on a NER (assigned in this run)"] == f["ports on a NER"] == 5
    ner = next(r for r in wb["NERs and ports"].iter_rows(min_row=2, values_only=True)
               if r[0] == "NER_20.1")
    assert ner[7] == 5 and ner[10] == 1 and ner[11] == 1
