from scripts import build


class FakeHTTPResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_provider_http_status_uses_default_verified_tls(monkeypatch):
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append(kwargs)
        return FakeHTTPResponse()

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)

    status = build._http_status(
        "https://api.telnyx.com/v2/balance",
        {"Authorization": "Bearer test-token"},
    )

    assert status == 200
    assert calls, "urlopen was called"
    assert "context" not in calls[0], "provider API calls must keep default verified TLS"


def test_internal_omar_health_probe_is_the_only_cert_none_use(monkeypatch, tmp_path):
    contexts = []

    def fake_urlopen(req, **kwargs):
        contexts.append(kwargs.get("context"))
        return FakeHTTPResponse()

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(build.Path, "home", lambda: tmp_path)

    result = build.health_probe("qg.omar.paris")

    assert result["status"] == "ok"
    assert contexts == [build._INTERNAL_OMAR_PARIS_SSL]
    assert build._INTERNAL_OMAR_PARIS_SSL.verify_mode == build.ssl.CERT_NONE


def test_unregistered_omar_subdomain_keeps_default_verified_tls(monkeypatch, tmp_path):
    calls = []

    def fake_urlopen(req, **kwargs):
        calls.append({"kwargs": kwargs, "headers": dict(req.header_items())})
        return FakeHTTPResponse()

    token_dir = tmp_path / ".config" / "oa-hub"
    token_dir.mkdir(parents=True)
    (token_dir / "machine-token").write_text("machine-secret", encoding="utf-8")
    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(build.Path, "home", lambda: tmp_path)

    result = build.health_probe("evil.omar.paris")

    assert result["status"] == "ok"
    assert calls[0]["kwargs"] == {"timeout": 8}
    header_names = {name.lower() for name in calls[0]["headers"]}
    assert "x-oa-token" not in header_names
