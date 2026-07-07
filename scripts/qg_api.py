#!/usr/bin/env python3
"""qg-api — API de la boîte de décisions (qg#27).

Bind sur l'IP tailnet uniquement (= inaccessible du public, par construction).
POST réponse → enregistre + débloque le processus en attente :
  - blocked_ref carte kanban t_xxx : comment "RÉPONSE ALEX" + unblock
    (le dispatcher cron respawne le worker qui reprend avec la réponse)
  - blocked_ref issue repo#n : gh issue comment + retrait label a-trancher
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "var" / "decisions.json"
HOST, PORT = "100.79.68.6", 8097
HERMES = "/home/omar/.local/bin/hermes"  # chemin absolu: PATH systemd ne contient pas ~/.local/bin
ISSUE_RE = re.compile(r"^([a-z0-9-]+)#(\d+)$")


def load() -> list[dict]:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save(items: list[dict]) -> None:
    STORE.parent.mkdir(exist_ok=True)
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    STORE.write_text(payload, encoding="utf-8")
    # Reflet IMMÉDIAT dans la page publique servie (sinon lag jusqu'au rebuild 30 min — fix 12/06)
    pub = ROOT / "public" / "api" / "decisions.json"
    try:
        if pub.parent.exists():
            pub.write_text(payload, encoding="utf-8")
    except Exception:
        pass


def _collect_feedback_alex(ref: str, answer: str) -> dict:
    """Best-effort: réponse /blocages négative → carte triage locale/dry-run.

    Le collecteur ne doit jamais casser l'API live: toute erreur revient en
    statut local, sans exposer le contenu brut au-delà de l'extrait redacted du
    module collect_feedback_alex.
    """
    try:
        path = ROOT / "scripts" / "collect_feedback_alex.py"
        spec = importlib.util.spec_from_file_location("collect_feedback_alex", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("collect_feedback_alex introuvable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.maybe_collect(ref, answer)
    except Exception as exc:
        return {"action": "feedback_collect_failed", "error": f"{exc.__class__.__name__}: {str(exc)[:120]}"}


def unblock(ref: str, qid: str, answer: str) -> str:
    if not ref:
        return "no_ref"
    if ref.startswith("t_"):
        subprocess.run([HERMES, "kanban", "comment", ref,
                        f"RÉPONSE ALEX ({qid}) : {answer}"], capture_output=True, timeout=30)
        r = subprocess.run([HERMES, "kanban", "unblock", ref], capture_output=True, text=True, timeout=30)
        return "kanban_unblocked" if r.returncode == 0 else f"kanban_error:{r.stderr.strip()[:80]}"
    m = ISSUE_RE.match(ref)
    if m:
        repo = f"omar-paris/omar-{m.group(1)}" if not m.group(1).startswith("omar-") else f"omar-paris/{m.group(1)}"
        subprocess.run(["gh", "issue", "comment", m.group(2), "-R", repo,
                        "-b", f"RÉPONSE ALEX ({qid}) : {answer}"], capture_output=True, timeout=30)
        subprocess.run(["gh", "issue", "edit", m.group(2), "-R", repo,
                        "--remove-label", "a-trancher"], capture_output=True, timeout=30)
        return "issue_commented"
    return "ref_inconnue"


class Handler(BaseHTTPRequestHandler):
    server_version = "QGDecisionsAPI/0.1"

    def _send(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        if self.path.startswith("/api/decisions"):
            self._send(200, load())
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        # Réponse directe à un blocage depuis /blocages/ (Alex 06/07) :
        # « fait » ou explication → commentaire + déblocage de la ref
        # (carte kanban t_xxx ou issue repo#n) via le même helper que les
        # décisions. Le système reprend la main derrière.
        if self.path == "/api/blocages/answer":
            try:
                length = int(self.headers.get("content-length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                ref, answer = str(data["ref"]).strip(), str(data["answer"]).strip()
                if not ref or not answer:
                    raise ValueError("ref et answer requis")
            except Exception as exc:
                self._send(422, {"error": str(exc)})
                return
            result = unblock(ref, "blocage", answer)
            feedback = _collect_feedback_alex(ref, answer)
            self._send(200, {"ref": ref, "answer": answer, "deblocage": result, "feedback_alex": feedback})
            return
        if self.path != "/api/decisions/answer":
            self._send(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            qid, answer = str(data["id"]), str(data["answer"]).strip()
            if not answer:
                raise ValueError("réponse vide")
        except Exception as exc:
            self._send(422, {"error": str(exc)})
            return
        items = load()
        for q in items:
            if q["id"] == qid and q["statut"] == "ouverte":
                q.update(statut="répondue", reponse=answer,
                         repondue_le=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                q["deblocage"] = unblock(q.get("blocked_ref", ""), qid, answer)
                save(items)
                self._send(200, q)
                return
        self._send(404, {"error": "question inconnue ou déjà répondue"})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"qg-api decisions sur http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
