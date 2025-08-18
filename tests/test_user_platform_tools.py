import pytest

from delinea_mcp import user_platform_tools


class DummyResponse:
    def __init__(self, status_code=200, data=None, text="tx"):
        self.status_code = status_code
        self._data = data or {"ok": True}
        self.text = text

    def json(self):
        return self._data


class DummyMCP:
    def __init__(self):
        self.names = []

    def tool(self):
        def deco(func):
            self.names.append(func.__name__)
            return func

        return deco


def test_build_headers_and_cache(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    monkeypatch.setattr(user_platform_tools, "platform_service_account", "a")
    monkeypatch.setattr(user_platform_tools, "platform_service_password", "p")
    monkeypatch.setattr(user_platform_tools, "platform_tenant_id", "tenant")
    post_calls = []

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        return DummyResponse(data={"access_token": "tok"})

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    headers = user_platform_tools._build_headers()
    assert headers["Authorization"] == "Bearer tok"
    assert "X-MT-SecondaryId" in headers
    # second call uses cached headers
    again = user_platform_tools._build_headers()
    assert again is headers
    assert len(post_calls) == 1


def test_platform_user_functions(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return DummyResponse()

    monkeypatch.setattr(user_platform_tools.requests, "post", fake_post)
    res = user_platform_tools.platform_user_management("create", data={"Name": "u"})
    assert res == {"result": {"ok": True}, "verification": {"ok": True}}
    res = user_platform_tools.platform_user_management("delete", user_id="id")
    assert res == {"result": {"ok": True}, "verification": {"ok": True}}
    res = user_platform_tools.platform_user_management(
        "update", user_id="id", data={"a": 1}
    )
    assert res == {"result": {"ok": True}, "verification": {"ok": True}}
    res = user_platform_tools.platform_user_management("search", username="u")
    assert res == {"ok": True}
    assert len(calls) == 7
    assert "CreateUser" in calls[0][0]


def test_platform_user_get(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return DummyResponse()

    monkeypatch.setattr(user_platform_tools.requests, "get", fake_get)
    res = user_platform_tools.platform_user_management("get", user_id="x")
    assert res == {"ok": True}
    assert "GetUser" in calls[0][0]


def test_register(monkeypatch):
    dummy = DummyMCP()
    user_platform_tools.register(dummy)
    assert {"platform_user_management"} <= set(dummy.names)


def test_build_headers_error(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "h")
    monkeypatch.setattr(user_platform_tools, "platform_service_account", "a")
    monkeypatch.setattr(user_platform_tools, "platform_service_password", "p")

    def bad_post(url, **kwargs):
        return DummyResponse(status_code=400, text="fail")

    monkeypatch.setattr(user_platform_tools.requests, "post", bad_post)
    with pytest.raises(RuntimeError):
        user_platform_tools._build_headers()


def test_create_user_nonjson(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    class BadResponse(DummyResponse):
        def json(self):
            raise ValueError

    monkeypatch.setattr(
        user_platform_tools.requests, "post", lambda *a, **k: BadResponse()
    )
    res = user_platform_tools.platform_user_management("create", data={"Name": "u"})
    assert res == {"result": {"error": "tx"}, "verification": {"error": "tx"}}


def test_other_calls_nonjson(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", {"h": 1})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "host")

    class Bad(DummyResponse):
        def json(self):
            raise ValueError

    monkeypatch.setattr(user_platform_tools.requests, "post", lambda *a, **k: Bad())
    assert user_platform_tools.platform_user_management("delete", user_id="x") == {
        "result": {"error": "tx"},
        "verification": {"error": "tx"},
    }
    assert user_platform_tools.platform_user_management(
        "update", user_id="x", data={}
    ) == {
        "result": {"error": "tx"},
        "verification": {"error": "tx"},
    }
    assert user_platform_tools.platform_user_management("search", username="x") == {
        "error": "tx"
    }


def test_configure_updates_globals(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "h")
    monkeypatch.setattr(user_platform_tools, "platform_service_account", "a")
    monkeypatch.setattr(user_platform_tools, "platform_service_password", "p")
    monkeypatch.setattr(user_platform_tools, "platform_tenant_id", "t")
    user_platform_tools.configure("H", "A", "P", "T")
    assert user_platform_tools.platform_hostname == "H"
    assert user_platform_tools.platform_service_account == "A"
    assert user_platform_tools.platform_service_password == "P"
    assert user_platform_tools.platform_tenant_id == "T"
