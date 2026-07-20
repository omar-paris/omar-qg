#!/usr/bin/env python3
"""qg_ingest — réception durable oa.vps-report/v1 + ACK oa.qg-ack/v1.

Contrat MVP QG-100:
- accepte uniquement l'enveloppe push `oa.vps-report/v1` (epoch + sequence) ;
- persiste dans une base SQLite dédiée/propre, séparée des bases de console ;
- répond seulement après commit durable avec `oa.qg-ack/v1` ;
- calcule les gaps par (deployment_id, stream_id, producer_epoch).

Preuve d'identité transport:
- mode direct: certificat client réel lu depuis la socket TLS Python (`getpeercert()`) ;
- mode proxy: headers d'identité acceptés uniquement si le mode proxy est activé
  explicitement ET si le proxy joint une signature HMAC contrôlée par secret.

Un appel HTTP direct qui forge `x-oa-client-cert-subject` reste donc rejeté.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var" / "qg-ingest" / "qg-ingest.sqlite3"
ALLOWED_STREAMS = {"heartbeat", "verdicts", "expected-work", "error-fingerprint", "oa-cost"}
ALLOWED_CLASSIFICATIONS = {"heartbeat", "verdict", "expected-work", "error-fingerprint", "oa-cost"}
ALLOWED_RETENTION = {"short", "standard", "long"}
REQUIRED_FIELDS = {
    "schema_name",
    "schema_version",
    "event_id",
    "deployment_id",
    "stream_id",
    "producer_epoch",
    "sequence",
    "occurred_at",
    "sent_at",
    "payload_hash",
    "data_classification",
    "retention_class",
    "key_id",
    "signature",
    "payload",
}
ALLOWED_FIELDS = REQUIRED_FIELDS | {"priority"}
PROXY_CERT_HEADERS = (
    "x-oa-client-cert-subject",
    "x-forwarded-client-cert",
    "ssl-client-subject-dn",
)
PROXY_SIGNATURE_HEADER = "x-oa-proxy-signature"


class IngestError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ClientIdentity:
    deployment_id: str
    source: str


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def db_path() -> Path:
    return Path(os.environ.get("QG_INGEST_DB", str(DEFAULT_DB))).expanduser()


def require_mtls() -> bool:
    return os.environ.get("QG_INGEST_REQUIRE_MTLS", "1").strip().lower() not in {"0", "false", "no", "off"}


def init_db(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id TEXT NOT NULL,
          deployment_id TEXT NOT NULL,
          stream_id TEXT NOT NULL,
          producer_epoch INTEGER NOT NULL,
          sequence INTEGER NOT NULL,
          occurred_at TEXT NOT NULL,
          sent_at TEXT NOT NULL,
          received_at TEXT NOT NULL,
          payload_hash TEXT NOT NULL,
          data_classification TEXT NOT NULL,
          retention_class TEXT NOT NULL,
          key_id TEXT NOT NULL,
          signature TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          client_identity_source TEXT NOT NULL,
          UNIQUE(deployment_id, stream_id, producer_epoch, sequence),
          UNIQUE(event_id)
        )
        """
    )
    conn.commit()
    return conn


def _header_get(headers: Mapping[str, str] | Any, name: str) -> str:
    if not hasattr(headers, "get"):
        return ""
    return str(headers.get(name, "") or headers.get(name.title(), "") or "").strip()


def _certificate_deployment_id(peer_cert: Mapping[str, Any]) -> ClientIdentity | None:
    subject = peer_cert.get("subject") or ()
    for rdn in subject:
        for key, value in rdn:
            if str(key).lower() == "commonname" and str(value).strip():
                return ClientIdentity(deployment_id=str(value).strip(), source="peer_cert.commonName")
    serial = str(peer_cert.get("serialNumber") or "").strip()
    if serial:
        return ClientIdentity(deployment_id=f"cert:{serial[-12:]}", source="peer_cert.serial")
    return None


def _proxy_headers_enabled() -> bool:
    return _env_flag("QG_INGEST_TRUST_PROXY_HEADERS")


def _signed_proxy_identity(headers: Mapping[str, str] | Any) -> ClientIdentity | None:
    """Accepte un header proxy seulement s'il est signé par un proxy contrôlé.

    Le header d'identité seul est volontairement insuffisant: il peut être forgé
    par n'importe quel client HTTP direct. La signature attendue est
    `sha256=<hmac_sha256(secret, identity)>` où `identity` est la valeur exacte
    du header d'identité retenu.
    """
    if not _proxy_headers_enabled():
        return None
    secret = os.environ.get("QG_INGEST_PROXY_SHARED_SECRET", "")
    if not secret:
        return None
    signature = _header_get(headers, PROXY_SIGNATURE_HEADER)
    if not signature.startswith("sha256="):
        return None
    provided = signature.removeprefix("sha256=").strip()

    for header in PROXY_CERT_HEADERS:
        value = _header_get(headers, header)
        if not value:
            continue
        expected = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(provided, expected):
            return ClientIdentity(deployment_id=value[:160], source=f"signed_proxy:{header}")
    return None


def client_identity(headers: Mapping[str, str] | Any, peer_cert: Mapping[str, Any] | None) -> ClientIdentity | None:
    """Extracte une preuve d'identité non spoofable par header HTTP direct."""
    if peer_cert:
        identity = _certificate_deployment_id(peer_cert)
        if identity:
            return identity
    return _signed_proxy_identity(headers)


def validate_event(event: Mapping[str, Any], identity: ClientIdentity | None = None) -> dict[str, Any]:
    missing = sorted(REQUIRED_FIELDS - set(event.keys()))
    if missing:
        raise IngestError(422, "missing_fields", "champs requis absents: " + ", ".join(missing))
    extra = sorted(set(event.keys()) - ALLOWED_FIELDS)
    if extra:
        raise IngestError(422, "extra_fields", "champs non autorisés: " + ", ".join(extra))

    if event.get("schema_name") != "oa.vps-report" or event.get("schema_version") != 1:
        raise IngestError(422, "schema", "schema attendu: oa.vps-report/v1")
    if event.get("stream_id") not in ALLOWED_STREAMS:
        raise IngestError(422, "stream", "stream_id non autorisé")
    if event.get("data_classification") not in ALLOWED_CLASSIFICATIONS:
        raise IngestError(422, "classification", "data_classification non autorisée")
    if event.get("retention_class") not in ALLOWED_RETENTION:
        raise IngestError(422, "retention", "retention_class non autorisée")

    deployment_id = str(event.get("deployment_id") or "").strip()
    stream_id = str(event.get("stream_id") or "").strip()
    event_id = str(event.get("event_id") or "").strip()
    if not deployment_id or not stream_id or not event_id:
        raise IngestError(422, "identity", "event_id/deployment_id/stream_id requis")
    if identity and identity.deployment_id not in {deployment_id, f"CN={deployment_id}"}:
        raise IngestError(403, "mtls_deployment_mismatch", "deployment_id ne correspond pas à l'identité mTLS")

    for field in ("producer_epoch", "sequence"):
        value = event.get(field)
        if not isinstance(value, int) or value < 0:
            raise IngestError(422, field, f"{field} doit être un entier >= 0")
    if not isinstance(event.get("payload"), dict):
        raise IngestError(422, "payload", "payload doit être un objet")

    payload_json = json.dumps(event["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    expected_hash = "sha256:" + hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if str(event.get("payload_hash")) != expected_hash:
        raise IngestError(422, "payload_hash", "payload_hash invalide")

    normalized = dict(event)
    normalized["payload_json"] = payload_json
    normalized["raw_json"] = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return normalized


def _compute_gaps(conn: sqlite3.Connection, deployment_id: str, stream_id: str, producer_epoch: int) -> list[list[int]]:
    rows = conn.execute(
        """
        SELECT sequence FROM events
        WHERE deployment_id=? AND stream_id=? AND producer_epoch=?
        ORDER BY sequence ASC
        """,
        (deployment_id, stream_id, producer_epoch),
    ).fetchall()
    sequences = [int(r[0]) for r in rows]
    if not sequences:
        return []
    gaps: list[list[int]] = []
    prev = sequences[0]
    if prev > 0:
        gaps.append([0, prev - 1])
    for seq in sequences[1:]:
        if seq > prev + 1:
            gaps.append([prev + 1, seq - 1])
        prev = seq
    return gaps


def accepted_through(conn: sqlite3.Connection, deployment_id: str, stream_id: str, producer_epoch: int) -> int:
    rows = conn.execute(
        """
        SELECT sequence FROM events
        WHERE deployment_id=? AND stream_id=? AND producer_epoch=?
        ORDER BY sequence ASC
        """,
        (deployment_id, stream_id, producer_epoch),
    ).fetchall()
    expected = 0
    accepted = -1
    for (seq,) in rows:
        seq = int(seq)
        if seq == expected:
            accepted = seq
            expected += 1
        elif seq > expected:
            break
    return accepted


def persist_event(event: Mapping[str, Any], conn: sqlite3.Connection | None = None, identity_source: str = "test") -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or init_db()
    duplicate = False
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO events (
                  event_id, deployment_id, stream_id, producer_epoch, sequence,
                  occurred_at, sent_at, received_at, payload_hash, data_classification,
                  retention_class, key_id, signature, payload_json, raw_json,
                  client_identity_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    event["deployment_id"],
                    event["stream_id"],
                    event["producer_epoch"],
                    event["sequence"],
                    event["occurred_at"],
                    event["sent_at"],
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    event["payload_hash"],
                    event["data_classification"],
                    event["retention_class"],
                    event["key_id"],
                    event["signature"],
                    event["payload_json"],
                    event["raw_json"],
                    identity_source,
                ),
            )
    except sqlite3.IntegrityError:
        duplicate = True

    gaps = _compute_gaps(conn, event["deployment_id"], event["stream_id"], int(event["producer_epoch"]))
    ack = {
        "schema_name": "oa.qg-ack",
        "schema_version": 1,
        "deployment_id": event["deployment_id"],
        "stream_id": event["stream_id"],
        "accepted_through": accepted_through(conn, event["deployment_id"], event["stream_id"], int(event["producer_epoch"])),
        "gaps": gaps,
        "duplicates": [int(event["sequence"])] if duplicate else [],
        "quarantined": [],
    }
    if own_conn:
        conn.close()
    return ack


def handle_ingest(
    raw_body: bytes,
    headers: Mapping[str, str] | Any,
    peer_cert: Mapping[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> tuple[int, dict[str, Any]]:
    identity = client_identity(headers, peer_cert)
    if require_mtls() and identity is None:
        raise IngestError(401, "mtls_required", "certificat client mTLS réel ou proxy signé requis")
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise IngestError(400, "json", f"JSON invalide: {exc}") from exc
    if not isinstance(event, dict):
        raise IngestError(422, "json_object", "payload racine doit être un objet")
    normalized = validate_event(event, identity=identity)
    ack = persist_event(normalized, conn=conn, identity_source=identity.source if identity else "mtls-disabled")
    return 200, ack


def mtls_server_context() -> ssl.SSLContext | None:
    """Contexte TLS optionnel pour déploiement direct sans reverse-proxy.

    Variables: QG_INGEST_TLS_CERT, QG_INGEST_TLS_KEY, QG_INGEST_TLS_CA.
    Sans ces trois chemins, l'API peut rester HTTP pour les routes décisions,
    mais l'ingest refuse l'identité mTLS tant qu'aucun peer_cert réel ou proxy
    explicitement signé n'est présenté.
    """
    cert = os.environ.get("QG_INGEST_TLS_CERT")
    key = os.environ.get("QG_INGEST_TLS_KEY")
    ca = os.environ.get("QG_INGEST_TLS_CA")
    if not (cert and key and ca):
        return None
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    return ctx
