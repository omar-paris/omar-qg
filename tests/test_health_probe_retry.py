"""Anti-récidive probe santé single-shot (carte t_928c3ec6 → t_a4f00112).

Le probe `health_probe()` de scripts/build.py était single-shot : la moindre
exception transitoire (timeout, reset TCP, handshake TLS) produisait
`{"status": "error", "http_code": None}` et donc une carte ALERTE pour un
domaine sain (landing.omar.paris, 2026-10-06, carte restée ouverte 36 j).

Ces tests figent le contrat : retry BORNÉ (3 tentatives, backoff fixe), et
échec explicite (`attempts`, `last_error`) quand la panne est réelle — un
retry ne doit jamais masquer un domaine réellement down.
"""
import urllib.error

from scripts import build


class FakeHTTPResponse:
    status = 200

    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _no_backoff(monkeypatch):
    monkeypatch.setattr(build, "HEALTH_PROBE_BACKOFF_SECONDS", 0)


def test_probe_ok_first_try_does_not_retry(monkeypatch):
    """(a) probe ok du premier coup -> aucune tentative supplémentaire."""
    _no_backoff(monkeypatch)
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        return FakeHTTPResponse(200)

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    result = build.health_probe("evil.omar.paris")

    assert result["status"] == "ok"
    assert result["http_code"] == 200
    assert result["attempts"] == 1
    assert len(calls) == 1, "un probe réussi ne doit pas être rejoué"


def test_transient_failure_then_success_is_ok_without_alert(monkeypatch):
    """(b) échec transitoire puis succès -> status ok, attempts=2."""
    _no_backoff(monkeypatch)
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return FakeHTTPResponse(200)

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    result = build.health_probe("evil.omar.paris")

    assert result["status"] == "ok", "un timeout transitoire ne doit pas produire d'alerte"
    assert result["http_code"] == 200
    assert result["attempts"] == 2
    assert len(calls) == 2
    assert "last_error" not in result


def test_definitive_failure_keeps_error_with_explicit_fields(monkeypatch):
    """(c) échec définitif -> status error, attempts borné, last_error explicite."""
    _no_backoff(monkeypatch)
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        raise ConnectionResetError("connection reset by peer")

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    result = build.health_probe("evil.omar.paris")

    assert result["status"] == "error", "un domaine réellement down doit toujours alerter"
    assert result["http_code"] is None
    assert result["attempts"] == 3, "le retry doit rester borné à 3 tentatives"
    assert len(calls) == 3
    assert "ConnectionResetError" in result["last_error"]


def test_retry_count_is_bounded_by_module_constant(monkeypatch):
    """Le nombre de tentatives est piloté par la constante, jamais infini."""
    _no_backoff(monkeypatch)
    monkeypatch.setattr(build, "HEALTH_PROBE_MAX_ATTEMPTS", 2)
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        raise OSError("boom")

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    result = build.health_probe("evil.omar.paris")

    assert result["status"] == "error"
    assert result["attempts"] == 2
    assert len(calls) == 2


def test_backoff_sleeps_between_attempts_only(monkeypatch):
    """Le backoff est appliqué entre les tentatives, pas après la dernière."""
    sleeps = []
    monkeypatch.setattr(build, "HEALTH_PROBE_BACKOFF_SECONDS", 2)
    monkeypatch.setattr(build.time, "sleep", lambda s: sleeps.append(s))

    def fake_urlopen(req, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    build.health_probe("evil.omar.paris")

    assert sleeps == [2, 2], "3 tentatives -> 2 backoffs, jamais un 3e"


def test_server_error_is_retried_then_reported(monkeypatch):
    """Un 502 transitoire (redémarrage) est rejoué ; un 502 persistant alerte."""
    _no_backoff(monkeypatch)
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)
        return FakeHTTPResponse(200)

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    recovered = build.health_probe("evil.omar.paris")
    assert recovered["status"] == "ok"
    assert recovered["attempts"] == 2

    calls.clear()

    def always_502(req, **kwargs):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(build.urllib.request, "urlopen", always_502)
    failed = build.health_probe("evil.omar.paris")

    assert failed["status"] == "error"
    assert failed["http_code"] == 502
    assert failed["attempts"] == 3
    assert "502" in failed["last_error"]


def test_client_error_is_not_retried(monkeypatch):
    """Un 4xx est une réponse applicative réelle : pas de retry, pas d'alerte."""
    _no_backoff(monkeypatch)
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    result = build.health_probe("evil.omar.paris")

    assert result["status"] == "ok"
    assert result["http_code"] == 404
    assert result["attempts"] == 1
    assert len(calls) == 1
