"""Contrat unique de qualification de pression swap pour les observateurs OA.

L'occupation du swap décrit une capacité consommée, pas une pression active. Une
alerte P1 exige donc, en plus d'un swap élevé, soit une RAM disponible basse,
soit de la pression PSI mémoire, soit des swap-outs soutenus. Les swap-ins seuls
sont volontairement ignorés : ils peuvent ne relire que des pages froides.
"""
from __future__ import annotations

import re
from typing import Any

RAM_AVAIL_WARN_MB = 1_024
MEMORY_PSI_WARN = 0.10
SWAP_OUT_KBPS_WARN = 128


def psi_memory_avg10(psi_output: str) -> float:
    """Retourne le plus haut avg10 de PSI mémoire ``some``/``full``."""
    values = [
        float(value)
        for value in re.findall(r"(?:some|full) avg10=([0-9.]+)", psi_output)
    ]
    return max(values, default=0.0)


def sustained_swap_out_kbps(vmstat_output: str) -> int:
    """Retourne le minimum des deux derniers débits ``so`` de vmstat.

    Exiger deux échantillons consécutifs évite de confondre un pic ponctuel avec
    un swap-out durable. ``si`` n'est pas lu : les page-ins froids ne sont pas
    un signal de pression à eux seuls.
    """
    headers: list[str] | None = None
    samples: list[list[str]] = []
    for line in vmstat_output.splitlines():
        columns = line.split()
        if "si" in columns and "so" in columns:
            headers = columns
            continue
        if headers and len(columns) == len(headers) and all(
            value.lstrip("-").isdigit() for value in columns
        ):
            samples.append(columns)
    if not headers or len(samples) < 2:
        return 0
    so_index = headers.index("so")
    return min(int(sample[so_index]) for sample in samples[-2:])


def classify_swap_pressure(
    available_mb: int | None,
    psi_output: str,
    vmstat_output: str,
) -> dict[str, Any]:
    """Qualifie les signaux de pression réels, indépendamment du taux de swap."""
    psi_avg10 = psi_memory_avg10(psi_output)
    swap_out_kbps = sustained_swap_out_kbps(vmstat_output)
    low_available = available_mb is not None and available_mb < RAM_AVAIL_WARN_MB
    memory_pressure = psi_avg10 >= MEMORY_PSI_WARN
    sustained_swap_out = swap_out_kbps >= SWAP_OUT_KBPS_WARN
    return {
        "low_available": low_available,
        "memory_pressure": memory_pressure,
        "sustained_swap_out": sustained_swap_out,
        "psi_avg10": psi_avg10,
        "swap_out_kbps": swap_out_kbps,
    }


def is_real_swap_pressure(signals: dict[str, Any]) -> bool:
    """Une P1 swap exige au moins un signal actif, jamais le taux brut seul."""
    return any(
        signals[name]
        for name in ("low_available", "memory_pressure", "sustained_swap_out")
    )
