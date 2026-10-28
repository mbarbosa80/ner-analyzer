"""Every React hook of a screen is called before the screen's first early
return (4.6.1).

React counts a component's hooks on every render and refuses a render that
calls more of them than the one before ("Minified React error #310"). In
4.6.0 the Import screen declared its upload queue *after* ``if (!p) return``:
opened with no project, then given one, it called one hook more and the
screen was replaced by "This screen could not be drawn" — on the first screen
anyone sees after choosing a project. The interface tests never saw it because
they all started with a project already chosen.

This scans every component in the interface's source: at the component's own
indentation, no ``useX(`` call may follow a ``return`` that is not the
component's last one.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"

_COMPONENT = re.compile(r"^(?:export )?function ([A-Z]\w*)\s*\(")
_HOOK = re.compile(r"^  (?:const [^=]+=\s*)?(use[A-Z]\w*)\s*[(<]")
_EARLY_RETURN = re.compile(r"^  if \(.*\)\s*(?:\{\s*)?return\b")
_IF_BLOCK = re.compile(r"^  if \(.*\) \{$")


def _components(text: str):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _COMPONENT.match(lines[i])
        if not m:
            i += 1
            continue
        name, start = m.group(1), i
        i += 1
        while i < len(lines) and lines[i] != "}":
            i += 1
        yield name, start, lines[start:i]


def _offences():
    out = []
    for path in sorted(SRC.rglob("*.tsx")):
        for name, start, body in _components(path.read_text(encoding="utf-8")):
            returned_at = None
            for k, line in enumerate(body):
                block_return = (_IF_BLOCK.match(line) and k + 1 < len(body)
                                and body[k + 1].lstrip().startswith("return"))
                if returned_at is None and (_EARLY_RETURN.match(line) or block_return):
                    returned_at = start + k + 1
                    continue
                hm = _HOOK.match(line)
                if hm and returned_at is not None:
                    out.append(f"{path.relative_to(SRC)}:{start + k + 1} {name}: "
                               f"{hm.group(1)} after the early return on line {returned_at}")
    return out


def test_no_hook_is_called_after_an_early_return():
    assert _offences() == []


def test_the_scanner_finds_the_4_6_0_defect(tmp_path, monkeypatch):
    """The check is proved on the shape that broke 4.6.0."""
    bad = tmp_path / "Bad.tsx"
    bad.write_text(
        "export function SetupPanel({ ctx }: any) {\n"
        "  const [a, setA] = useState(0);\n"
        "  if (!p) return <div />;\n"
        "  const [queue, setQueue] = useState<{ name: string }[]>([]);\n"
        "  return <div />;\n"
        "}\n", encoding="utf-8")
    import sys
    monkeypatch.setattr(sys.modules[__name__], "SRC", tmp_path)
    found = _offences()
    assert len(found) == 1 and "useState after the early return on line 3" in found[0]


def test_the_scanner_reads_every_screen():
    names = {n for p in SRC.rglob("*.tsx")
             for n, _, _ in _components(p.read_text(encoding="utf-8"))}
    for must in ("SetupPanel", "Viewer", "DemandPanel", "ProjectsPanel"):
        assert must in names, must
