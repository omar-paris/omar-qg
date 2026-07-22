#!/usr/bin/env python3
"""Format a scoped Telegram summary from an OA Observer markdown report."""

from __future__ import annotations

import re
import sys
from pathlib import Path


BILAN_RE = re.compile(r"Bilan\s*:\s*(\d+)\s*P0.*?(\d+)\s*P1.*?(\d+)\s*P2")
TITLE_RE = re.compile(r"^###\s*\[(P0|P1)\]\s*(.+?)\s*·", re.MULTILINE)
OBS_RE = re.compile(r"##\s*💬\s*Observations.*?\n(.*)", re.DOTALL)
SCOPE_NOTICE = "Ce scan observateur ne vaut pas état global Kanban/gates/capacité."


def format_brief(brief: str, source: str) -> str:
    match = BILAN_RE.search(brief)
    if match is None:
        counts = None
    else:
        counts = tuple(int(value) for value in match.groups())

    titles = TITLE_RE.findall(brief)
    observations_match = OBS_RE.search(brief)
    observations = observations_match.group(1).strip() if observations_match else ""

    lines = ["Salut Alex 👋 — briefing observateur du jour."]
    if counts is None:
        lines.append("\n🔴 Bilan P0/P1 illisible : verdict global interdit.")
    else:
        p0, p1, _p2 = counts
        if p0:
            lines.append(f"\n🔴 {p0} P0 détecté(s) dans ce scan :")
            lines.extend(f"• {title}" for severity, title in titles if severity == "P0")
        elif p1:
            lines.append(f"\n🟠 Aucun P0 détecté dans ce scan, mais {p1} P1 reste(nt) à surveiller.")
        else:
            lines.append("\n✅ Aucun P0/P1 détecté dans ce scan partiel.")

        p1_titles = [title for severity, title in titles if severity == "P1"]
        if p1_titles:
            lines.append("\n🟠 P1 : " + " · ".join(p1_titles[:5]))

    lines.append("\n⚠️ " + SCOPE_NOTICE)
    if observations:
        lines.append("\n💬 " + observations[:600])
    lines.append(f"\nDétail : {source}")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} BRIEF.md", file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    print(format_brief(source.read_text(encoding="utf-8"), str(source)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
