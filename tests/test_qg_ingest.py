import hashlib
import hmac
import json
from email.message import Message

import pytest

from scripts import qg_ingest


def event(sequence, *, deployment_id="oa-master", epoch=7, payload=None):
    payload = payload or {"kind": "heartbeat", "status": "ok"}
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_name": "oa.vps-report",
        "schema_version": 1,
        "event_id": f"{deployment_id}-heartbeat-{epoch}-{sequence}",
        "deployment_id": deployment_id,
        "stream_id": "heartbeat",
        "producer_epoch": epoch,
        "sequence": sequence,
        "occurred_at": "2026-07-20T00:00:00Z",
        "sent_at": "2026-07-20T00:00:01Z",
        "payload_hash": "sha256:" + hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        "data_classification": "heartbeat",
        "retention_class": "short",
        "key_id": "test-key",
        "signature": "test-signature",
        "payload": payload,
    }


def signed_proxy_headers(deployment_id="oa-master", secret="test-proxy-secret"):
    h = Message()
    h["x-oa-client-cert-subject"] = deployment_id
    h["x-oa-proxy-signature"] = "sha256=" + hmac.new(
        secret.encode("utf-8"), deployment_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return h


def peer_cert_for(deployment_id="oa-master"):
    return {"subject": ((('commonName', deployment_id),),)}


def test_header_spoof_is_rejected_when_no_tls_or_trusted_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    monkeypatch.delenv("QG_INGEST_TRUST_PROXY_HEADERS", raising=False)
    monkeypatch.delenv("QG_INGEST_PROXY_SHARED_SECRET", raising=False)
    headers = Message()
    headers["x-oa-client-cert-subject"] = "oa-master"

    with pytest.raises(qg_ingest.IngestError) as err:
        qg_ingest.handle_ingest(json.dumps(event(0)).encode("utf-8"), headers, peer_cert=None)

    assert err.value.status == 401
    assert err.value.code == "mtls_required"


def test_direct_peer_cert_persists_heartbeat_and_returns_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    raw = json.dumps(event(0)).encode("utf-8")

    status, ack = qg_ingest.handle_ingest(raw, {}, peer_cert=peer_cert_for())

    assert status == 200
    assert ack == {
        "schema_name": "oa.qg-ack",
        "schema_version": 1,
        "deployment_id": "oa-master",
        "stream_id": "heartbeat",
        "accepted_through": 0,
        "gaps": [],
        "duplicates": [],
        "quarantined": [],
    }

    conn = qg_ingest.init_db(tmp_path / "clean-qg-ingest.sqlite3")
    rows = conn.execute(
        "SELECT deployment_id, stream_id, producer_epoch, sequence, client_identity_source FROM events"
    ).fetchall()
    conn.close()
    assert rows == [("oa-master", "heartbeat", 7, 0, "peer_cert.commonName")]


def test_unsigned_proxy_header_is_rejected_even_when_proxy_mode_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    monkeypatch.setenv("QG_INGEST_TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("QG_INGEST_PROXY_SHARED_SECRET", "test-proxy-secret")
    headers = Message()
    headers["x-oa-client-cert-subject"] = "oa-master"

    with pytest.raises(qg_ingest.IngestError) as err:
        qg_ingest.handle_ingest(json.dumps(event(0)).encode("utf-8"), headers, peer_cert=None)

    assert err.value.status == 401
    assert err.value.code == "mtls_required"


def test_signed_proxy_identity_can_ingest_when_explicitly_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    monkeypatch.setenv("QG_INGEST_TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("QG_INGEST_PROXY_SHARED_SECRET", "test-proxy-secret")

    status, ack = qg_ingest.handle_ingest(
        json.dumps(event(0)).encode("utf-8"),
        signed_proxy_headers(),
        peer_cert=None,
    )

    assert status == 200
    assert ack["accepted_through"] == 0
    conn = qg_ingest.init_db(tmp_path / "clean-qg-ingest.sqlite3")
    rows = conn.execute("SELECT client_identity_source FROM events").fetchall()
    conn.close()
    assert rows == [("signed_proxy:x-oa-client-cert-subject",)]


def test_ingest_detects_gap_after_simulated_cut(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    cert = peer_cert_for()
    qg_ingest.handle_ingest(json.dumps(event(0)).encode("utf-8"), {}, peer_cert=cert)

    status, ack = qg_ingest.handle_ingest(json.dumps(event(2)).encode("utf-8"), {}, peer_cert=cert)

    assert status == 200
    assert ack["accepted_through"] == 0
    assert ack["gaps"] == [[1, 1]]

    _, healed_ack = qg_ingest.handle_ingest(json.dumps(event(1)).encode("utf-8"), {}, peer_cert=cert)
    assert healed_ack["accepted_through"] == 2
    assert healed_ack["gaps"] == []


def test_duplicate_sequence_is_acknowledged_but_not_reinserted(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    raw = json.dumps(event(0)).encode("utf-8")
    cert = peer_cert_for()
    qg_ingest.handle_ingest(raw, {}, peer_cert=cert)

    _, ack = qg_ingest.handle_ingest(raw, {}, peer_cert=cert)

    assert ack["duplicates"] == [0]
    conn = qg_ingest.init_db(tmp_path / "clean-qg-ingest.sqlite3")
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    assert count == 1


def test_mtls_identity_is_required_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))

    with pytest.raises(qg_ingest.IngestError) as err:
        qg_ingest.handle_ingest(json.dumps(event(0)).encode("utf-8"), {}, peer_cert=None)

    assert err.value.status == 401
    assert err.value.code == "mtls_required"


def test_payload_hash_is_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))
    bad = event(0)
    bad["payload_hash"] = "sha256:deadbeef"

    with pytest.raises(qg_ingest.IngestError) as err:
        qg_ingest.handle_ingest(json.dumps(bad).encode("utf-8"), {}, peer_cert=peer_cert_for())

    assert err.value.status == 422
    assert err.value.code == "payload_hash"


def test_mtls_identity_must_match_payload_deployment_id(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_INGEST_DB", str(tmp_path / "clean-qg-ingest.sqlite3"))

    with pytest.raises(qg_ingest.IngestError) as err:
        qg_ingest.handle_ingest(
            json.dumps(event(0, deployment_id="oa-master")).encode("utf-8"),
            {},
            peer_cert=peer_cert_for("other-vps"),
        )

    assert err.value.status == 403
    assert err.value.code == "mtls_deployment_mismatch"
