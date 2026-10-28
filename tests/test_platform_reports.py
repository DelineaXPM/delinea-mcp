"""Unit tests for ``platform_reports`` (Platform Insights > Reports)."""

import json

import pytest

from delinea_mcp import user_platform_tools
from delinea_mcp.annotations import TOOL_ANNOTATIONS


class DummyResponse:
    def __init__(self, status_code=200, data=None, text="tx"):
        self.status_code = status_code
        self._data = {"ok": True} if data is None else data
        self.text = text

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


LOGIN_DEFINITION = {
    "service": "Identity",
    "name": "User Last Login Report",
    "description": "Latest logins to the platform for a given time window.",
    "timeToLive": -1,
    "isAsync": False,
    "callbacks": [{"url": "/identity/api/users", "headers": {"Authorization": ["x"]}}],
    "frontEndConfiguration": {
        "form": {
            "inputs": [
                {
                    "inputType": "Text",
                    "label": "Email Address",
                    "configuration": {
                        "required": False,
                        "filterParameter": "UserLoginData.email",
                        "defaultValue": None,
                        "operatorOptions": ["Contains"],
                    },
                },
                {
                    "inputType": "DatePeriod",
                    "label": "Last Login Range",
                    "configuration": {
                        "required": True,
                        "filterParameter": "UserLoginData.DatePeriod",
                        "strategy": "DateRange",
                        "configuration": {
                            "startDateFilterParameter": "UserLoginData.lastLoginFrom",
                            "endDateFilterParameter": "UserLoginData.lastLoginTo",
                        },
                    },
                },
                {
                    "inputType": "Role",
                    "label": "Role Name",
                    "configuration": {
                        "required": True,
                        "filterParameter": "FetchMembersOfRole.id",
                        "allowMultiple": False,
                    },
                },
            ]
        },
        "gridColumnModels": [
            {
                "columnName": "User Name",
                "columnType": "Text",
                "isSortable": True,
                "propertyMap": "UserLoginData.name",
                "template": None,
            },
            {
                "columnName": "Last Login",
                "columnType": "Date",
                "isSortable": False,
                "propertyMap": "UserLoginData.lastLogin",
            },
        ],
    },
}


@pytest.fixture
def platform(monkeypatch):
    """Configure a fake tenant and capture every HTTP call."""
    monkeypatch.setattr(user_platform_tools, "_headers", {"Authorization": "Bearer t"})
    monkeypatch.setattr(user_platform_tools, "platform_hostname", "tenant.example")
    calls = []
    state = {"response": DummyResponse()}

    def fake(method):
        def _call(url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return state["response"]

        return _call

    monkeypatch.setattr(user_platform_tools.requests, "get", fake("GET"))
    monkeypatch.setattr(user_platform_tools.requests, "post", fake("POST"))
    return calls, state


def test_list_builds_query_parameters(platform):
    calls, state = platform
    state["response"] = DummyResponse(data={"totalCount": 1, "reportDefinitions": []})
    out = user_platform_tools.platform_reports(
        "list", query="login", service="Identity", page=2, page_size=5
    )
    assert out == {"totalCount": 1, "reportDefinitions": []}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == (
        "https://tenant.example/report/api/report/report-definitions"
    )
    assert calls[0]["params"] == {
        "RecordsPerPage": 5,
        "PageNumber": 2,
        "SearchText": "login",
        "Service.Eq": "Identity",
    }
    assert calls[0]["headers"] == {"Authorization": "Bearer t"}


def test_describe_compacts_definition_and_quotes_name(platform):
    calls, state = platform
    state["response"] = DummyResponse(data=LOGIN_DEFINITION)
    out = user_platform_tools.platform_reports("describe", "User Last Login Report")
    assert calls[0]["url"].endswith(
        "/report/api/report/report-definitions/User%20Last%20Login%20Report"
    )
    assert "callbacks" not in out and "frontEndConfiguration" not in out
    assert out["name"] == "User Last Login Report"
    assert out["service"] == "Identity"
    assert out["is_async"] is False
    text, dates, role = out["inputs"]
    assert text == {
        "label": "Email Address",
        "type": "Text",
        "required": False,
        "parameter": "UserLoginData.email",
        "operators": ["Contains"],
    }
    assert dates["required"] is True
    assert "parameter" not in dates
    assert dates["start_parameter"] == "UserLoginData.lastLoginFrom"
    assert dates["end_parameter"] == "UserLoginData.lastLoginTo"
    assert "ISO-8601" in dates["value_format"]
    assert role["parameter"] == "FetchMembersOfRole.id"
    assert role["allow_multiple"] is False
    assert out["columns"] == [
        {
            "name": "User Name",
            "type": "Text",
            "property": "UserLoginData.name",
            "sortable": True,
        },
        {
            "name": "Last Login",
            "type": "Date",
            "property": "UserLoginData.lastLogin",
            "sortable": False,
        },
    ]


def test_run_normalises_filters_and_pages(platform):
    calls, state = platform
    state["response"] = DummyResponse(
        data={"data": [{"name": "kevin"}], "totalCount": 1, "reportDefinitionName": "x"}
    )
    ready_made = {
        "filterValue": {
            "filterType": "Text",
            "stringValue": "a",
            "filterParameterKey": "k",
        }
    }
    out = user_platform_tools.platform_reports(
        "run",
        "Top 10 Viewers of Secrets",
        [
            {
                "parameter": "UserLoginData.email",
                "value": "kevin",
                "operator": "Contains",
                "label": "Email Address",
            },
            {"parameter": "bare", "value": 7, "type": "Number"},
            ready_made,
        ],
        page=3,
        page_size=25,
    )
    assert out["data"] == [{"name": "kevin"}]
    call = calls[0]
    assert call["method"] == "POST"
    assert call["timeout"] == user_platform_tools._REPORT_RUN_TIMEOUT
    assert calls and call["timeout"] >= user_platform_tools._DEFAULT_TIMEOUT
    assert call["url"].endswith(
        "/report-definitions/Top%2010%20Viewers%20of%20Secrets/results"
    )
    assert call["json"] == {
        "reportDefinitionName": "Top 10 Viewers of Secrets",
        "filterValues": [
            {
                "filterValue": {
                    "filterType": "Text",
                    "stringValue": "kevin",
                    "filterParameterKey": "email",
                },
                "callbackName": "UserLoginData",
                "operatorValue": "Contains",
                "displayName": "Email Address",
            },
            {
                "filterValue": {
                    "filterType": "Number",
                    "stringValue": "7",
                    "filterParameterKey": "bare",
                }
            },
            ready_made,
        ],
        "pagination": {"recordsPerPage": 25, "pageNumber": 3},
    }


def test_run_accepts_dict_shorthand_and_json_string(platform):
    calls, state = platform
    user_platform_tools.platform_reports(
        "run",
        "r",
        {"UserLoginData.name": "kevin", "UserLoginData.lastLoginFrom": "2026-10-01"},
    )
    values = calls[0]["json"]["filterValues"]
    assert [v["filterValue"]["filterParameterKey"] for v in values] == [
        "name",
        "lastLoginFrom",
    ]
    assert all(v["callbackName"] == "UserLoginData" for v in values)
    assert values[1]["filterValue"]["stringValue"] == "2026-10-01"

    user_platform_tools.platform_reports(
        "run", "r", json.dumps([{"parameter": "a.b", "value": None}])
    )
    assert calls[1]["json"]["filterValues"] == [
        {
            "filterValue": {
                "filterType": "Text",
                "stringValue": "",
                "filterParameterKey": "b",
            },
            "callbackName": "a",
        }
    ]
    assert calls[1]["json"]["pagination"] == {"recordsPerPage": 50, "pageNumber": 1}

    user_platform_tools.platform_reports("run", "r", None)
    assert calls[2]["json"]["filterValues"] == []


@pytest.mark.parametrize(
    "filters, message",
    [
        ("{not json", "Invalid JSON data"),
        ("42", "filters must be a list"),
        ([1], "each filter must be an object"),
        ([{"value": "x"}], "needs a 'parameter'"),
    ],
)
def test_run_rejects_malformed_filters(platform, filters, message):
    calls, _ = platform
    out = user_platform_tools.platform_reports("run", "r", filters)
    assert message in out["error"]
    assert calls == []


def test_argument_validation_happens_before_any_request(platform):
    calls, _ = platform
    assert "Unknown action" in user_platform_tools.platform_reports("schedule")["error"]
    assert (
        "report name required" in user_platform_tools.platform_reports("run")["error"]
    )
    assert (
        "report name required"
        in user_platform_tools.platform_reports("describe")["error"]
    )
    assert (
        "snapshot_id required"
        in user_platform_tools.platform_reports("snapshot_results")["error"]
    )
    assert (
        "positive integers"
        in user_platform_tools.platform_reports("list", page="x")["error"]
    )
    assert calls == []


def test_not_configured_returns_guidance(monkeypatch):
    monkeypatch.setattr(user_platform_tools, "_headers", None)
    monkeypatch.setattr(user_platform_tools, "platform_hostname", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_account", None)
    monkeypatch.setattr(user_platform_tools, "platform_service_password", None)
    out = user_platform_tools.platform_reports("list")
    assert "Platform is not configured" in out["error"]


def test_run_server_error_carries_detail_and_hint(platform):
    _, state = platform
    body = {"error": "An error occurred while retrieving report data"}
    state["response"] = DummyResponse(status_code=500, data=body)
    out = user_platform_tools.platform_reports(
        "run", "What members are assigned to a role"
    )
    assert out["error"] == "Platform report API returned HTTP 500"
    assert out["detail"] == body
    assert "describe" in out["hint"]


def test_unknown_report_404_hint_and_non_json_body(platform):
    _, state = platform
    state["response"] = DummyResponse(
        status_code=404, data=ValueError("no json"), text="nf"
    )
    out = user_platform_tools.platform_reports("describe", "Nope")
    assert out["error"] == "Platform report API returned HTTP 404"
    assert out["detail"] == {"error": "nf"}
    assert "Unknown report" in out["hint"]


def test_snapshot_actions_build_urls(platform):
    calls, state = platform
    state["response"] = DummyResponse(data={"reportRuns": [], "totalCount": 0})
    user_platform_tools.platform_reports("snapshots", query="mfa", page_size=10)
    assert calls[0]["url"].endswith("/report/api/report/report-snapshots")
    assert calls[0]["params"] == {
        "RecordsPerPage": 10,
        "PageNumber": 1,
        "SearchText": "mfa",
    }

    state["response"] = DummyResponse(
        data={"reportRunSnapshotData": [], "totalCount": 0}
    )
    out = user_platform_tools.platform_reports("snapshot_results", snapshot_id="id/1")
    assert out == {"reportRunSnapshotData": [], "totalCount": 0}
    assert calls[1]["url"].endswith(
        "/report/api/report/report-snapshots/id%2F1/results"
    )
    assert calls[1]["params"] == {"RecordsPerPage": 50, "PageNumber": 1}


def test_transport_exception_becomes_error(platform, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(user_platform_tools.requests, "get", boom)
    out = user_platform_tools.platform_reports("list")
    assert out == {"error": "connection reset"}


def test_registered_with_read_only_annotation():
    names = [name for name, _ in user_platform_tools.TOOLS]
    assert "platform_reports" in names
    assert TOOL_ANNOTATIONS["platform_reports"].read_only_hint is True
