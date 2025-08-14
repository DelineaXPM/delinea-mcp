import pytest

from delinea_mcp import tools


class DummySession:
    def request(self, *a, **kw):
        raise AssertionError("network")


@pytest.mark.parametrize("data,expected", [('{"a":1}', {"a": 1}), (None, None)])
def test_parse_json_data_ok(data, expected):
    assert tools._parse_json_data(data) == expected


def test_parse_json_data_bad():
    with pytest.raises(ValueError):
        tools._parse_json_data("{")


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.user_management, ("get",), "user_id required for get"),
        (tools.user_management, ("update",), "user_id and data required for update"),
        (tools.user_management, ("delete",), "user_id required for delete"),
        (tools.user_management, ("reset_2fa",), "user_id required for reset_2fa"),
        (
            tools.user_management,
            ("reset_password",),
            "user_id and data required for reset_password",
        ),
        (tools.user_management, ("lock_out",), "user_id required for lock_out"),
    ],
)
def test_user_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.role_management, ("get",), "role_id required for get"),
        (tools.role_management, ("update",), "role_id and data required for update"),
    ],
)
def test_role_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


def test_role_management_unknown(monkeypatch):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = tools.role_management("xxx")
    assert result["error"] == "Unknown action: xxx"


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.user_role_management, ("add", 1, None), "role_ids required for add"),
        (
            tools.user_role_management,
            ("remove", 1, None),
            "role_ids required for remove",
        ),
    ],
)
def test_user_role_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


def test_user_role_management_unknown(monkeypatch):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = tools.user_role_management("xxx", 1)
    assert result["error"] == "Unknown action: xxx"


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.group_management, ("get",), "group_id required for get"),
        (tools.group_management, ("delete",), "group_id required for delete"),
    ],
)
def test_group_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


def test_group_management_unknown(monkeypatch):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = tools.group_management("xxx")
    assert result["error"] == "Unknown action: xxx"


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.user_group_management, ("add", 1, None), "group_ids required for add"),
        (
            tools.user_group_management,
            ("remove", 1, None),
            "group_ids required for remove",
        ),
    ],
)
def test_user_group_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


def test_user_group_management_unknown(monkeypatch):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = tools.user_group_management("xxx", 1)
    assert result["error"] == "Unknown action: xxx"


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.group_role_management, ("add", 1, None), "role_ids required for add"),
        (
            tools.group_role_management,
            ("remove", 1, None),
            "role_ids required for remove",
        ),
    ],
)
def test_group_role_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


def test_group_role_management_unknown(monkeypatch):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = tools.group_role_management("xxx", 1)
    assert result["error"] == "Unknown action: xxx"


@pytest.mark.parametrize(
    "func,args,msg",
    [
        (tools.folder_management, ("get",), "folder_id required for get"),
        (
            tools.folder_management,
            ("update",),
            "folder_id and data required for update",
        ),
        (tools.folder_management, ("delete",), "folder_id required for delete"),
    ],
)
def test_folder_management_missing(monkeypatch, func, args, msg):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = func(*args)
    assert result["error"] == msg


def test_folder_management_unknown(monkeypatch):
    monkeypatch.setattr(tools, "delinea", DummySession())
    result = tools.folder_management("xxx")
    assert result["error"] == "Unknown action: xxx"
