#!/usr/bin/env python3
"""qg-api — API de la boîte de décisions (qg#27).

Bind sur l'IP tailnet uniquement (= inaccessible du public, par construction).
POST réponse → enregistre + débloque le processus en attente :
  - blocked_ref carte kanban t_xxx : comment "RÉPONSE ALEX" + unblock
    (le dispatcher cron respawne le worker qui reprend avec la réponse)
  - blocked_ref issue repo#n : gh issue comment + retrait label a-trancher
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "var" / "decisions.json"
HOST, PORT = "100.79.68.6", 8097
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


def unblock(ref: str, qid: str, answer: str) -> str:
    if not ref:
        return "no_ref"
    if ref.startswith("t_"):
        subprocess.run(["hermes", "kanban", "comment", ref,
                        f"RÉPONSE ALEX ({qid}) : {answer}"], capture_output=True, timeout=30)
        r = subprocess.run(["hermes", "kanban", "unblock", ref], capture_output=True, text=True, timeout=30)
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
