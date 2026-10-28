"""Where does the marked-up PDF actually spend its time and memory?"""
import sys, time, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
try:
    import psutil; P = psutil.Process()
    def mb(): return P.memory_info().rss / 1e6
except Exception:
    def mb(): return -1.0

def step(label, t0, m0):
    print(f"{label:<38} {time.time()-t0:7.1f}s   RSS {mb():7.0f} MB  (+{mb()-m0:.0f})", flush=True)
    return time.time(), mb()

t, m = time.time(), mb()
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Project
from app import services as S
from app.config import settings
from app.domain.reports import export_marked_pdf
t, m = step("imports", t, m)

db = SessionLocal()
p = db.execute(select(Project)).scalars().first()
t, m = step("open db", t, m)

scales = S.scale_map(db, p.id);                    t, m = step("scale_map", t, m)
ners = S.register_ners(db, p);                     t, m = step(f"register_ners ({len(ners)})", t, m)
areas = S.collect_areas(db, p);                    t, m = step(f"collect_areas ({len(areas)})", t, m)
net = S.build_route_network(db, p, scales);        t, m = step("build_route_network", t, m)
from app.domain.coverage import compute_coverage
result = compute_coverage(areas=areas, ners=ners, scale_for_page=scales,
                          rules=S.distance_rules(p), network=net)
t, m = step(f"compute_coverage ({len(result.assignments)})", t, m)

out = settings.exports_dir / f"project_{p.id}" / "PROFILE_marked.pdf"
stray = []
export_marked_pdf(p.drawings[0].stored_path, str(out), coverage=result, ners=ners,
                  scale_for_page=scales, rules=S.distance_rules(p),
                  scenario="As-Is", off_page=stray)
t, m = step("export_marked_pdf", t, m)
print(f"saida {os.path.getsize(out)/1e6:.1f} MB, {len(stray)} fora da pagina")
db.close()
