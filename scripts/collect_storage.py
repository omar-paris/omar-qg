#!/usr/bin/env python3
"""collect_storage.py — read-only storage/backup summary for OA QG.

Produces public-safe JSON: no secrets, no raw logs, no file contents.
It measures mounts, known high-entropy directories, Hermes DB backup retention,
and configured rclone remotes names only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_API = ROOT / "public" / "api" / "ops"

MOUNTS = [
    {"path": "/", "label": "Root VPS", "target_pct": 75, "warn_pct": 75, "crit_pct": 85, "role": "OS + runtime actif"},
    {"path": "/mnt/HC_Volume_105618057", "label": "Volume 1 chaud", "target_pct": 80, "warn_pct": 80, "crit_pct": 90, "role": "offload chaud, caches, backups récents"},
    {"path": "/mnt/HC_Volume_105618059", "label": "Volume 2 froid", "target_pct": 80, "warn_pct": 80, "crit_pct": 90, "role": "tampon/archive locale"},
]

TRACKED_DIRS = [
    {"path": "/home/omar/.hermes", "label": "Hermes runtime", "kind": "runtime", "budget_mb": 7500},
    {"path": "/home/omar/.hermes/backups", "label": "Hermes backups symlink", "kind": "backup", "budget_mb": 700},
    {"path": "/home/omar/.hermes/kanban/workspaces", "label": "Kanban workspaces", "kind": "workspace", "budget_mb": 2000},
    {"path": "/mnt/HC_Volume_105618057/oa-offload-home-cache", "label": "Caches offload home", "kind": "cache", "budget_mb": 8000},
    {"path": "/mnt/HC_Volume_105618057/oa-offload-hermes-backups", "label": "Backups Hermes offload", "kind": "backup", "budget_mb": 7000},
    {"path": "/mnt/HC_Volume_105618057/omar-offloaded-backups", "label": "Backups migration/offload", "kind": "archive", "budget_mb": 6000},
    {"path": "/mnt/HC_Volume_105618057/onedrive_BIZNESS", "label": "OneDrive mirror/cache", "kind": "cloud-cache", "budget_mb": 9000},
]

BACKUP_DIR = Path("/mnt/HC_Volume_105618057/oa-offload-hermes-backups/hermes-dbs")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def status_from_pct(pct: int | None, warn: int, crit: int) -> str:
    if pct is None:
        return "unknown"
    if pct >= crit:
        return "critical"
    if pct >= warn:
        return "warning"
    return "ok"


def bytes_h(n: int | None) -> str:
    if n is None:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.1f}{u}" if u != "B" else f"{int(v)}B"
        v /= 1024
    return f"{n}B"


def measure_mount(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["path"])
    base = {**spec, "exists": path.exists()}
    if not path.exists():
        return {**base, "status": "unknown", "used_pct": None, "total_bytes": None, "used_bytes": None, "free_bytes": None}
    try:
        du = shutil.disk_usage(path)
        used = du.total - du.free
        pct = round((used / du.total) * 100) if du.total else None
        return {
            **base,
            "status": status_from_pct(pct, spec["warn_pct"], spec["crit_pct"]),
            "used_pct": pct,
            "total_bytes": du.total,
            "used_bytes": used,
            "free_bytes": du.free,
            "total_h": bytes_h(du.total),
            "used_h": bytes_h(used),
            "free_h": bytes_h(du.free),
        }
    except Exception as exc:
        return {**base, "status": "unknown", "error": str(exc)[:160]}


def du_mb(path: str) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        out = subprocess.check_output(["du", "-sm", "--", str(p)], text=True, stderr=subprocess.DEVNULL, timeout=30)
        return int(out.split()[0])
    except Exception:
        return None


def measure_dir(spec: dict[str, Any]) -> dict[str, Any]:
    size = du_mb(spec["path"])
    budget = int(spec.get("budget_mb") or 0)
    if size is None:
        status = "unknown"
    elif budget and size > budget:
        status = "warning"
    else:
        status = "ok"
    return {
        **spec,
        "exists": Path(spec["path"]).exists(),
        "size_mb": size,
        "size_h": f"{size/1024:.1f}GB" if isinstance(size, int) and size >= 1024 else (f"{size}MB" if size is not None else "—"),
        "status": status,
    }


def backup_summary() -> dict[str, Any]:
    """Return public-safe aggregate backup health.

    Do not expose archive names, absolute paths, or raw mtimes in the public QG API.
    """
    archives = []
    if BACKUP_DIR.exists():
        for p in sorted(BACKUP_DIR.glob("hermes-dbs-*.tgz"), key=lambda x: x.stat().st_mtime):
            try:
                archives.append({
                    "size_bytes": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                    "checksum_exists": Path(str(p) + ".sha256").exists(),
                })
            except Exception:
                continue
    total = sum(a["size_bytes"] for a in archives)
    latest = archives[-1] if archives else None
    latest_age_hours = None
    if latest:
        latest_age_hours = round(max(0, time.time() - latest["mtime"]) / 3600, 1)
    latest_checksum_exists = bool(latest and latest.get("checksum_exists"))
    return {
        "name": "hermes_dbs",
        "exists": BACKUP_DIR.exists(),
        "retention_policy": "keep_last_14",
        "count": len(archives),
        "total_bytes": total,
        "total_h": bytes_h(total),
        "latest_age_hours": latest_age_hours,
        "latest_checksum_exists": latest_checksum_exists,
        "status": "ok" if 1 <= len(archives) <= 14 and latest_checksum_exists else ("warning" if archives else "critical"),
    }


def free_summary() -> dict[str, Any]:
    try:
        out = subprocess.check_output(["free", "-b"], text=True, stderr=subprocess.DEVNULL, timeout=10).splitlines()
        if len(out) < 3:
            raise ValueError("unexpected free output")
        mem = out[1].split()
        swap = out[2].split()
        def row(parts: list[str]) -> dict[str, Any]:
            total, used, free = int(parts[1]), int(parts[2]), int(parts[3])
            pct = round((used / total) * 100) if total else None
            return {"total_bytes": total, "used_bytes": used, "free_bytes": free, "used_pct": pct, "total_h": bytes_h(total), "used_h": bytes_h(used), "free_h": bytes_h(free)}
        mem_r = row(mem)
        swap_r = row(swap)
        swap_r["status"] = status_from_pct(swap_r.get("used_pct"), 60, 85)
        mem_r["status"] = status_from_pct(mem_r.get("used_pct"), 80, 92)
        return {"memory": mem_r, "swap": swap_r}
    except Exception as exc:
        return {"memory": {"status": "unknown"}, "swap": {"status": "unknown"}, "error": str(exc)[:160]}


def rclone_remotes() -> dict[str, Any]:
    try:
        out = subprocess.check_output(["rclone", "listremotes"], text=True, stderr=subprocess.DEVNULL, timeout=10)
        remotes = [line.rstrip(":") for line in out.splitlines() if line.strip()]
        return {"status": "ok" if remotes else "warning", "remotes": remotes, "note": "noms seulement, pas de listing contenu"}
    except FileNotFoundError:
        return {"status": "unknown", "remotes": [], "note": "rclone absent"}
    except Exception as exc:
        return {"status": "warning", "remotes": [], "note": str(exc)[:160]}


def _parse_size_to_bytes(value: str) -> int | None:
    value = (value or "").strip()
    if not value or value == "0B":
        return 0
    units = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
             "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
    import re
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)$", value)
    if not m:
        return None
    unit = m.group(2)
    if unit not in units:
        return None
    return int(float(m.group(1)) * units[unit])


def docker_summary() -> dict[str, Any]:
    """Return Docker image cleanup signal without treating Docker's raw reclaimable as actionable.

    `docker system df` can report large reclaimable bytes even when images are referenced by
    running containers or compose stacks. QG therefore separates theoretical hints from safe
    prune candidates proven by dangling images / stopped containers / unlinked volumes.
    """
    try:
        images_raw = subprocess.check_output(
            ["docker", "image", "ls", "--format", "{{json .}}"],
            text=True, stderr=subprocess.DEVNULL, timeout=20,
        )
        containers_raw = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            text=True, stderr=subprocess.DEVNULL, timeout=20,
        )
        dangling_raw = subprocess.check_output(
            ["docker", "image", "ls", "--filter", "dangling=true", "--format", "{{json .}}"],
            text=True, stderr=subprocess.DEVNULL, timeout=20,
        )
        df_raw = subprocess.check_output(["docker", "system", "df"], text=True, stderr=subprocess.DEVNULL, timeout=20)
    except FileNotFoundError:
        return {"status": "unknown", "note": "docker absent"}
    except Exception as exc:
        return {"status": "warning", "note": str(exc)[:160]}

    image_rows = [json.loads(line) for line in images_raw.splitlines() if line.strip()]
    container_rows = [json.loads(line) for line in containers_raw.splitlines() if line.strip()]
    dangling_rows = [json.loads(line) for line in dangling_raw.splitlines() if line.strip()]
    active_image_refs = {c.get("Image") for c in container_rows if c.get("Image")}
    running = [c for c in container_rows if str(c.get("State", "")).lower() == "running"]
    stopped = [c for c in container_rows if str(c.get("State", "")).lower() != "running"]

    dangling_bytes = 0
    for row in dangling_rows:
        dangling_bytes += _parse_size_to_bytes(str(row.get("Size", ""))) or 0

    theoretical = None
    for line in df_raw.splitlines():
        if line.startswith("Images"):
            parts = line.split()
            # Docker prints: Images TOTAL ACTIVE SIZE RECLAIMABLE...
            if len(parts) >= 5:
                theoretical = " ".join(parts[4:])
            break

    safe_to_prune = len(dangling_rows) > 0 or len(stopped) > 0
    status = "warning" if safe_to_prune else "ok"
    return {
        "status": status,
        "images_total": len(image_rows),
        "containers_total": len(container_rows),
        "containers_running": len(running),
        "containers_stopped": len(stopped),
        "active_image_refs": len(active_image_refs),
        "dangling_images": len(dangling_rows),
        "dangling_bytes": dangling_bytes,
        "dangling_h": bytes_h(dangling_bytes),
        "safe_to_prune": safe_to_prune,
        "theoretical_reclaimable_hint": theoretical,
        "interpretation": "Docker reclaimable brut non actionnable sans images dangling ou containers arrêtés prouvés.",
    }


def rollup_status(parts: Sequence[str | None]) -> str:
    if "critical" in parts:
        return "critical"
    if "warning" in parts:
        return "warning"
    if all(p == "ok" for p in parts if p):
        return "ok"
    return "unknown"


def collect() -> dict[str, Any]:
    mounts = [measure_mount(m) for m in MOUNTS]
    dirs = [measure_dir(d) for d in TRACKED_DIRS]
    backups = [backup_summary()]
    mem = free_summary()
    cloud = {"rclone": rclone_remotes()}
    docker = docker_summary()
    risks = []
    for m in mounts:
        if m.get("status") in {"warning", "critical"}:
            risks.append({"level": m["status"], "code": "MOUNT_PRESSURE", "message": f"{m['label']} à {m.get('used_pct')}% — cible {m.get('target_pct')}%"})
    for d in dirs:
        if d.get("status") == "warning":
            risks.append({"level": "warning", "code": "DIR_OVER_BUDGET", "message": f"{d['label']} {d.get('size_h')} > budget {d.get('budget_mb')}MB"})
    if mem.get("swap", {}).get("status") in {"warning", "critical"}:
        risks.append({"level": mem["swap"]["status"], "code": "SWAP_PRESSURE", "message": f"Swap utilisée à {mem['swap'].get('used_pct')}%"})
    if docker.get("safe_to_prune"):
        risks.append({"level": "warning", "code": "DOCKER_SAFE_PRUNE", "message": f"Docker a {docker.get('dangling_images')} images dangling et {docker.get('containers_stopped')} containers arrêtés"})

    statuses = [m.get("status") for m in mounts] + [b.get("status") for b in backups] + [mem.get("swap", {}).get("status"), docker.get("status")]
    recommended_actions = []
    if any(m.get("path") == "/mnt/HC_Volume_105618057" and m.get("status") != "ok" for m in mounts):
        recommended_actions.append("Réduire caches/offload ou archiver froid vers rclone:gog-crypt")
    if any(d.get("kind") == "cache" and d.get("status") == "warning" for d in dirs):
        recommended_actions.append("Revue caches offload home avant suppression ciblée")
    if mem.get("swap", {}).get("status") in {"warning", "critical"}:
        recommended_actions.append("Re-mesurer processus lourds puis recycler services ciblés avant swapoff/swappon")
    if docker.get("safe_to_prune"):
        recommended_actions.append("Docker: prune ciblé autorisable seulement sur dangling/stopped prouvés")

    return {
        "meta": {"schema_version": "0.1", "mode": "dynamic-readonly", "generated_at": now_iso(), "source": "scripts/collect_storage.py"},
        "status": rollup_status(statuses),
        "mounts": mounts,
        "memory": mem,
        "tracked_dirs": dirs,
        "backup_sets": backups,
        "cloud_archives": cloud,
        "docker": docker,
        "risks": risks,
        "recommended_actions": recommended_actions,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write public/api/ops/storage-summary.json")
    args = ap.parse_args()
    payload = collect()
    if args.write:
        PUBLIC_API.mkdir(parents=True, exist_ok=True)
        (PUBLIC_API / "storage-summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
