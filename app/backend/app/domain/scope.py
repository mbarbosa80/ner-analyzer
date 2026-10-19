"""Which TEAP spaces the study is about.

**The TEAP is the document that rules** (Marcelo, 17 Sep 2026): it says whether
an area is to be served at all. The check runs from the TEAP to the drawing and
never the other way round — a room that is on the drawing and not in the TEAP
is not a question this tool asks, however likely it looks that it will need
service one day.

The same rule has a second half. A TEAP space whose lines add up to **zero
network ports** asks for nothing a NER can give it, so it is left out of the
review queue, of *Demand per space*, of the exceptions and of the coverage
run. Left out, not deleted: the scope is worked out from the imported lines
every time it is asked for, so a later TEAP revision that gives the space a
port brings it back by itself, and the rows can be shown on request.

One exception, and it is there because of what the real TEAP contains. A
``Wired Connection`` line carries a quantity and **no ports** — the catalogue
counts the port on the device, not on the service. Where the requester brings
their own device there is no device line, and the port is never counted: on
HND that is 58 wired connections on the five *Photo Position FOP*
spaces, the demand the 70 m photographer limit exists for. Hiding those because
the arithmetic says zero would hide the most distance-sensitive rooms in the
venue. They stay in scope with zero ports — no port is invented — and carry a
note that says why they are on the list.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

#: A line that asks for a cable: "Wired Connection - Shared Internet Access",
#: "Wired Connection - Dedicated plug (RJ45) …", "… Wired LAN". Wireless lines
#: never match — and neither does an accessory that merely has a cable: the
#: catalogue's "Accessories - USB Wired Mouse" and "Wired Keyboard" are
#: peripherals, not network connections (a bare ``\bwired\b`` put every
#: mouse-only storage room into the study on the 2.8.0 test pass).
WIRED_REQUEST_RX = re.compile(
    r"\bwired\s+(?:connection|lan|network|internet|data|ethernet)\b|\brj[\s-]?45\b",
    re.IGNORECASE)


def wired_without_ports(lines: Optional[Iterable[dict]]) -> float:
    """How many wired connections the TEAP requests on lines that count no port."""
    total = 0.0
    for line in lines or []:
        if not isinstance(line, dict):
            continue
        try:
            qty = float(line.get("qty") or 0)
            ports = float(line.get("ports") or 0)
        except (TypeError, ValueError):
            continue
        if qty > 0 and ports <= 0 and WIRED_REQUEST_RX.search(str(line.get("product") or "")):
            total += qty
    return total


def teap_scope(total_ports: Optional[float],
               lines: Optional[Iterable[dict]]) -> tuple[bool, Optional[str]]:
    """``(in_scope, note)`` for one TEAP space.

    * ports requested → in scope, no note;
    * no ports, but wired connections requested → in scope, with the note;
    * no ports and nothing wired → out of scope.
    """
    if (total_ports or 0) > 0:
        return True, None
    wired = wired_without_ports(lines)
    if wired > 0:
        return True, (f"the TEAP requests {wired:g} wired connection(s) here and counts "
                      f"no network port for them — kept on the list at zero ports; "
                      f"validate the port count with the TEAP owner")
    return False, None
