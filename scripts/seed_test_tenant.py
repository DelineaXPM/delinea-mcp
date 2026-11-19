"""Seed a Secret Server tenant with the data the live tests expect.

Creates (or reuses) a "delinea-mcp tests" folder and a password secret in it,
and prints ``export LIVE_...=`` lines for the IDs the integration tests read.
Safe to re-run: existing objects with the same names are reused.

Reads the same environment as the server. With ``PLATFORM_HOSTNAME`` set and
``LIVE_SS_VIA_PLATFORM=1`` it signs in through the Platform.

    set -a; source .env.test-tenant.local; set +a
    python scripts/seed_test_tenant.py
"""

from __future__ import annotations

import os
import secrets
import sys

from delinea_mcp.api import DelineaSession
from delinea_mcp.tls import use_system_trust_store

FOLDER_NAME = "delinea-mcp tests"
SECRET_NAME = (
    "delinea-mcp test web password"  # nosec B105 - display name, not a credential
)
TEMPLATE_NAMES = ("Web Password", "Password")


def session() -> DelineaSession:
    via_platform = os.getenv("LIVE_SS_VIA_PLATFORM") == "1"
    if not via_platform:
        # DelineaSession treats platform_hostname="" as unset and falls back
        # to $PLATFORM_HOSTNAME, which would send the Secret Server password
        # to the Platform's sign-in endpoint.
        os.environ.pop("PLATFORM_HOSTNAME", None)
    return DelineaSession(
        base_url=os.environ["DELINEA_BASE_URL"],
        username=os.environ["DELINEA_USERNAME"],
        platform_hostname=os.environ["PLATFORM_HOSTNAME"] if via_platform else "",
    )


def find_template(s: DelineaSession) -> dict:
    for name in TEMPLATE_NAMES:
        found = s.request(
            "GET", "/v1/secret-templates", params={"filter.searchText": name}
        ).json()
        for record in found.get("records", []):
            if record.get("name") == name:
                return s.request("GET", f"/v1/secret-templates/{record['id']}").json()
    sys.exit(f"No template named {TEMPLATE_NAMES}; create one or edit this script")


def ensure_folder(s: DelineaSession) -> int:
    found = s.request(
        "GET", "/v1/folders", params={"filter.searchText": FOLDER_NAME}
    ).json()
    for record in found.get("records", []):
        if record.get("folderName") == FOLDER_NAME:
            return record["id"]
    stub = s.request("GET", "/v1/folders/stub").json()
    stub.update({"folderName": FOLDER_NAME, "parentFolderId": -1, "folderTypeId": 1})
    return s.request("POST", "/v1/folders", json=stub).json()["id"]


def ensure_secret(s: DelineaSession, template: dict, folder_id: int) -> int:
    found = s.request(
        "GET",
        "/v2/secrets",
        params={"filter.searchText": SECRET_NAME, "filter.folderId": folder_id},
    ).json()
    for record in found.get("records", []):
        if record.get("name") == SECRET_NAME:
            return record["id"]
    stub = s.request(
        "GET",
        "/v1/secrets/stub",
        params={"secretTemplateId": template["id"], "folderId": folder_id},
    ).json()
    # New tenants return siteId -1 in the stub; 1 is the built-in default site.
    site_id = stub.get("siteId") or 0
    stub.update(
        {
            "name": SECRET_NAME,
            "folderId": folder_id,
            "siteId": site_id if site_id > 0 else 1,
        }
    )
    for item in stub.get("items", []):
        slug = (item.get("slug") or "").lower()
        if item.get("isPassword"):
            item["itemValue"] = "Tst-" + secrets.token_urlsafe(12)
        elif slug == "username":
            item["itemValue"] = "e2e-user"
        elif slug in ("url", "resource"):
            item["itemValue"] = "https://example.com"
        elif slug == "notes":
            item["itemValue"] = "seeded by scripts/seed_test_tenant.py"
    return s.request("POST", "/v1/secrets", json=stub).json()["id"]


def pick_role(s: DelineaSession) -> int:
    roles = s.request("GET", "/v1/roles", params={"take": 50}).json()["records"]
    for preferred in ("User", "Basic User"):
        for role in roles:
            if role.get("name") == preferred:
                return role["id"]
    plain = [r for r in roles if "admin" not in (r.get("name") or "").lower()]
    return (plain or roles)[0]["id"]


def main() -> None:
    use_system_trust_store()
    s = session()
    template = find_template(s)
    fields = template.get("fields", [])
    password_field = next(f for f in fields if f.get("isPassword"))
    folder_id = ensure_folder(s)
    secret_id = ensure_secret(s, template, folder_id)
    user_id = s.request("GET", "/v1/users/current").json()["id"]
    ids = {
        "LIVE_FOLDER_ID": folder_id,
        "LIVE_SECRET_ID": secret_id,
        "LIVE_TEMPLATE_ID": template["id"],
        "LIVE_TEMPLATE_FIELD_ID": password_field.get("secretTemplateFieldId")
        or password_field.get("id"),
        "LIVE_USER_ID": user_id,
        "LIVE_ROLE_ID": pick_role(s),
    }
    for key, value in ids.items():
        print(f"export {key}={value}")


if __name__ == "__main__":
    main()
