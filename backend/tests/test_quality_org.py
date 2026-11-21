"""آزمون‌های v1.0.6: ویرایش کد سازمان + داشبورد کیفیت داده."""
from tests.conftest import dev_headers


def test_org_code_update(client, tenant1):
    r = client.post("/api/v1/organizations",
                    json={"type": "faculty", "code": "F90", "name": "دانشکده آزمون کد"},
                    headers=dev_headers(tenant=tenant1))
    assert r.status_code == 201, r.text
    org = r.json()

    r = client.patch(f"/api/v1/organizations/{org['id']}",
                     json={"code": "F91", "name": "دانشکده آزمون کد (ویرایش)"},
                     headers={**dev_headers(tenant=tenant1), "If-Match": f'"{org["version"]}"'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == "F91"
    assert body["name"] == "دانشکده آزمون کد (ویرایش)"
    assert body["version"] == org["version"] + 1


def test_org_code_duplicate_rejected(client, tenant1):
    for code in ("F80", "F81"):
        r = client.post("/api/v1/organizations",
                        json={"type": "faculty", "code": code, "name": f"دانشکده {code}"},
                        headers=dev_headers(tenant=tenant1))
        assert r.status_code == 201, r.text
        org = r.json() if code == "F81" else None
    r = client.patch(f"/api/v1/organizations/{org['id']}",
                     json={"code": "F80"},
                     headers={**dev_headers(tenant=tenant1), "If-Match": f'"{org["version"]}"'})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "ORG_DUPLICATE"


def test_quality_overview(client, tenant1):
    r = client.get("/api/v1/quality/overview", headers=dev_headers(tenant=tenant1))
    assert r.status_code == 200, r.text
    data = r.json()
    assert 0 <= data["score"] <= 100
    assert data["counts"]["checks"] == 17
    assert {d["key"] for d in data["dimensions"]} == {
        "completeness", "uniqueness", "integrity", "validity", "coverage", "freshness"}
    assert {d["key"] for d in data["domains"]} == {
        "persons", "organizations", "references", "mappings"}
    ids = {c["check_id"] for c in data["checks"]}
    assert "orgs_duplicate_code" in ids
    assert "persons_duplicate_verified_identifier" in ids
    assert "mappings_dangling_entity" in ids
    assert "refs_missing_estimated_capacity" in ids
    for c in data["checks"]:
        assert c["what"] and c["root_cause"] and c["fix_hint"]
        assert c["status"] in ("ok", "warn", "fail")


def test_quality_overview_requires_role(client, tenant1):
    r = client.get("/api/v1/quality/overview", headers=dev_headers(roles="auditor", tenant=tenant1))
    assert r.status_code == 200, r.text
