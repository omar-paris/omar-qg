#!/usr/bin/env python3
from __future__ import annotations

import json
from html import escape
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ACTIFS = Path("/home/omar/23-Offre/actifs")
VERSION = "V" + (ROOT / "VERSION").read_text(encoding="utf-8").strip()
DOMAIN = "qg.omar.paris"

CSS = """
:root{--bg:#020617;--panel:#0f172a;--panel2:#111827;--ink:#e5e7eb;--muted:#94a3b8;--line:#334155;--good:#22c55e;--warn:#f59e0b;--bad:#ef4444;--blue:#38bdf8;--violet:#a78bfa;--radius:18px}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#1e1b4b,#020617 42%);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.5}a{color:#7dd3fc}.top{position:sticky;top:0;background:rgba(2,6,23,.92);backdrop-filter:blur(16px);border-bottom:1px solid var(--line);z-index:5}.bar{max-width:1280px;margin:auto;padding:16px 20px;display:flex;justify-content:space-between;gap:20px;align-items:center}.brand{font-weight:950;letter-spacing:-.04em}.meta{color:var(--muted);font-size:12px;font-weight:800}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{padding:8px 12px;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--ink);font-size:13px;font-weight:800}.nav a.active{background:white;color:#020617}main{max-width:1280px;margin:auto;padding:42px 20px 80px}.hero{display:grid;grid-template-columns:1.25fr .75fr;gap:18px}.panel{background:rgba(15,23,42,.88);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 24px 80px rgba(0,0,0,.25)}.hero-main{padding:34px}.eyebrow{color:var(--blue);font-weight:950;text-transform:uppercase;letter-spacing:.1em;font-size:12px}.h1{font-size:clamp(38px,5vw,70px);line-height:.95;letter-spacing:-.07em;margin:10px 0}.summary{font-size:19px;color:#cbd5e1;max-width:820px}.stats{padding:22px;display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.stat{background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:15px;padding:15px}.stat strong{display:block;font-size:32px;letter-spacing:-.05em}.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:18px}.legend .panel{padding:18px}.registry{margin-top:22px;display:grid;gap:12px}.row{display:grid;grid-template-columns:1fr 130px 130px 120px 1.4fr;gap:10px;align-items:center;padding:16px;background:rgba(15,23,42,.9);border:1px solid var(--line);border-radius:16px}.row.header{position:sticky;top:68px;background:#111827;font-weight:950;color:#cbd5e1}.name{font-weight:950}.small{font-size:12px;color:var(--muted)}.pill{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:999px;padding:5px 9px;font-size:12px;font-weight:900}.pill.good{color:#bbf7d0;border-color:#166534;background:rgba(34,197,94,.12)}.pill.warn{color:#fde68a;border-color:#92400e;background:rgba(245,158,11,.12)}.pill.bad{color:#fecaca;border-color:#991b1b;background:rgba(239,68,68,.12)}.actions{display:flex;gap:8px;flex-wrap:wrap}.actions a{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:5px 9px;text-decoration:none}.footer{border-top:1px solid var(--line);padding:22px;text-align:center;color:var(--muted);font-size:13px}@media(max-width:900px){.hero{grid-template-columns:1fr}.row{grid-template-columns:1fr}.row.header{display:none}.bar{flex-direction:column;align-items:flex-start}}
"""

NAV = [("/", "Accueil"), ("/registry/", "Registry"), ("/changelog/", "Changelog")]

ITEMS = [
    {"id":"landing","name":"landing","domain":"landing.omar.paris","repo":"omar-paris/omar-landing","path":"omar-landing","scope":"CORE OA","role":"Vitrine publique. Explique et convainc. CTA cible : admin-app.","version":"V0.2.0","changelog":"https://landing.omar.paris/changelog/","live":"live","next":"Harmoniser contrat/version et CTA vers app.omar.paris."},
    {"id":"app","name":"admin-app / app","domain":"app.omar.paris","repo":"omar-paris/omar-app","path":"omar-app","scope":"CORE OA","role":"Portail client/prospect : onboarding, config, buy, SAV, factures, compte.","version":"V0.1.0","changelog":"https://app.omar.paris/changelog/","live":"runtime","next":"Persister Caddy/DNS puis rendre onboarding/config interactifs."},
    {"id":"catalogue","name":"catalogue","domain":"catalogue.omar.paris","repo":"omar-paris/omar-catalogue","path":"omar-catalogue","scope":"CORE OA","role":"Recommandations, Apps, Agents, Tools, Skills, MCP, Bundles.","version":"V0.7.3","changelog":"https://catalogue.omar.paris/changelog/","live":"runtime","next":"Persister Caddy/DNS normal ; enrichir recommandations."},
    {"id":"lab","name":"lab","domain":"lab.omar.paris","repo":"Plane upstream / oa-lab-plane local","path":"oa-lab-plane","scope":"CORE OA","role":"Atelier Plane : projets, work items, cycles, modules.","version":"Plane","changelog":"https://lab.omar.paris/","live":"live","next":"Poursuivre consolidation anciens projets vers CORE/VPS/DIVERS/ARCHIVE."},
    {"id":"qg","name":"qg","domain":"qg.omar.paris","repo":"omar-paris/omar-qg","path":"omar-qg","scope":"CORE OA","role":"Registry opérationnel : versions, état repos, liens, dettes.","version":"V0.1.0","changelog":"https://qg.omar.paris/changelog/","live":"runtime","next":"Connecter à données dynamiques plus tard ; ne pas copier Lab/Hub/Top."},
    {"id":"hub","name":"hub","domain":"hub.omar.paris","repo":"omar-paris/omar-hub","path":"omar-hub","scope":"VPS Hermes OA","role":"Cockpit local VPS ; Hub / Catalogue devient lien vers catalogue dédié.","version":"V0.8.5 public / VERSION stale 0.2.0","changelog":"https://hub.omar.paris/changelog/","live":"live","next":"Harmoniser VERSION ; commit/traiter public/api/omartop.json dirty."},
    {"id":"omartop","name":"OmarTop","domain":"top.omar.paris","repo":"omar-paris/omar-top","path":"omar-top","scope":"VPS Hermes OA","role":"Référence Stack VPS Hermes OA : standards, maturité, contrôles, Apps L1.","version":"0.3.0-rc1","changelog":"https://top.omar.paris/changelog/","live":"live","next":"Ajouter /changelog/ visible ; stabiliser rc1."},
]


def git_state(path_slug: str) -> dict:
    path = ACTIFS / path_slug
    if not path.exists():
        return {"exists": False, "branch": "missing", "dirty": False, "head": ""}
    def run(args):
        try:
            return subprocess.check_output(args, cwd=path, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    head = run(["git", "log", "-1", "--oneline"])
    status = run(["git", "status", "--short"])
    return {"exists": True, "branch": branch or "no-git", "dirty": bool(status), "head": head, "status_short": status.splitlines()[:8]}


def payload() -> dict:
    items=[]
    for item in ITEMS:
        enriched=dict(item)
        enriched["git"] = git_state(item["path"])
        items.append(enriched)
    counts = {
        "total": len(items),
        "core": sum(1 for i in items if i["scope"] == "CORE OA"),
        "vps": sum(1 for i in items if i["scope"] == "VPS Hermes OA"),
        "runtime_or_live": sum(1 for i in items if i["live"] in {"live", "runtime"}),
    }
    return {"version": VERSION, "domain": DOMAIN, "items": items, "counts": counts}


def cls(live: str) -> str:
    return "good" if live == "live" else "warn" if live == "runtime" else "bad"


def render_row(item: dict) -> str:
    dirty = "dirty" if item["git"].get("dirty") else "clean"
    dirty_cls = "warn" if dirty == "dirty" else "good"
    return f"""<article class="row"><div><div class="name">{escape(item['name'])}</div><div class="small">{escape(item['role'])}</div><div class="actions"><a href="https://{escape(item['domain'])}/">site</a><a href="https://github.com/{escape(item['repo'])}">repo</a><a href="{escape(item['changelog'])}">changelog</a></div></div><div><span class="pill {cls(item['live'])}">{escape(item['live'])}</span></div><div><span class="pill">{escape(item['version'])}</span></div><div><span class="pill {dirty_cls}">git {dirty}</span><div class="small">{escape(item['git'].get('branch',''))}</div></div><div><div>{escape(item['next'])}</div><div class="small">{escape(item['git'].get('head',''))}</div></div></article>"""


def render(route: str, title: str, summary: str, data: dict) -> str:
    nav = "".join(f'<a class="{"active" if href == route else ""}" href="{href}">{label}</a>' for href,label in NAV)
    stats = "".join(f'<div class="stat"><strong>{v}</strong><span>{escape(k)}</span></div>' for k,v in data["counts"].items())
    rows = "".join(render_row(i) for i in data["items"])
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} · OA QG</title><meta name="qg-version" content="{VERSION}"><link rel="stylesheet" href="/assets/styles.css"></head><body><header class="top"><div class="bar"><div><div class="brand">OA QG · {DOMAIN}</div><div class="meta">{VERSION} · CORE OA registry · read-only</div></div><nav class="nav">{nav}</nav></div></header><main><section class="hero"><div class="panel hero-main"><div class="eyebrow">CORE OA registry</div><h1 class="h1">{escape(title)}</h1><p class="summary">{escape(summary)}</p></div><aside class="panel stats">{stats}</aside></section><section class="legend"><div class="panel"><strong>Lab = atelier</strong><p class="small">Plane organise projets, cycles, modules, work items.</p></div><div class="panel"><strong>QG = registry</strong><p class="small">QG synthétise versions, états, liens et dettes CORE OA.</p></div><div class="panel"><strong>Hub/OmarTop = VPS Hermes OA</strong><p class="small">Hub et OmarTop restent la vérité VPS/runtime, pas copiés ici.</p></div></section><section class="registry"><article class="row header"><div>App / rôle</div><div>Live</div><div>Version</div><div>Git</div><div>Next action</div></article>{rows}</section></main><footer class="footer">OA QG · {DOMAIN} · {VERSION} · <a href="/api/core-repos.json">API</a> · <a href="/changelog/">Changelog</a></footer></body></html>"""


def main() -> None:
    data = payload()
    if PUBLIC.exists(): shutil.rmtree(PUBLIC)
    (PUBLIC / "assets").mkdir(parents=True)
    (PUBLIC / "api").mkdir(parents=True)
    (PUBLIC / "assets" / "styles.css").write_text(CSS, encoding="utf-8")
    (PUBLIC / "api" / "core-repos.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pages = {
        "/": ("Versions et état des Apps CORE OA", "Vue synthétique pour comprendre comment landing, admin-app, catalogue, Lab, QG, Hub et OmarTop s’articulent."),
        "/registry/": ("Registry repos CORE OA", "État Git, version, changelog, live status et prochaine action pour chaque surface."),
        "/changelog/": ("Changelog QG", "V0.1.0 : création du registry versions/états repos CORE OA."),
    }
    for route,(title,summary) in pages.items():
        out = PUBLIC / "index.html" if route == "/" else PUBLIC / route.strip("/") / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(route,title,summary,data), encoding="utf-8")
    print(f"built qg {len(pages)} routes, items={len(data['items'])}")

if __name__ == "__main__":
    main()
