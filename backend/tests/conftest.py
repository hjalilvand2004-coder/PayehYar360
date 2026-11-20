import os
import sys
import tempfile
import uuid as uuid_mod

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "examples", "sample_consumer"))

_tmp = tempfile.mkdtemp(prefix="core_test_")
os.environ.update({
    "ENV": "test",
    "DEV_AUTH": "true",
    "DATABASE_URL": f"sqlite:///{_tmp}/test_core.db",
    "AUTO_CREATE_TABLES": "true",
    "SEED_DEMO": "false",
    "WORKERS_IN_PROCESS": "false",
    "RATE_LIMIT_PER_MINUTE": "0",
    "CHANGE_RETENTION_MIN": "5",
    "SNAPSHOT_TTL_HOURS": "2",
    "DATA_DIR": _tmp,
    "RABBITMQ_URL": "",  # قطعی Broker در آزمون → رویدادها باید در Outbox بمانند
    "OIDC_ISSUER": "http://188.212.96.235:8086",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def dev_headers(user="steward1", roles="steward,tenant_admin", tenant="t1", name="Steward One",
                scopes="", service=None):
    h = {
        "X-Dev-User": user,
        "X-Dev-Name": name,
        "X-Dev-Roles": roles,
        "X-Dev-Tenants": tenant,
    }
    if scopes:
        h["X-Dev-Scopes"] = scopes
    if service:
        h["X-Dev-Service"] = service
    return h


@pytest.fixture(scope="session")
def tenant1(client):
    r = client.post("/api/v1/tenants", json={"code": "t1", "name": "دانشگاه آزمون ۱"},
                    headers=dev_headers(tenant="t1"))
    assert r.status_code == 201, r.text
    return "t1"


@pytest.fixture(scope="session")
def tenant2(client):
    r = client.post("/api/v1/tenants", json={"code": "t2", "name": "دانشگاه آزمون ۲"},
                    headers=dev_headers(tenant="t2"))
    assert r.status_code == 201, r.text
    return "t2"


@pytest.fixture()
def person1(client, tenant1):
    r = client.post("/api/v1/persons", json={"given_name": "علی", "family_name": "رضایی"},
                    headers=dev_headers(roles="master_data_editor", tenant=tenant1))
    assert r.status_code == 201, r.text
    return r.json()
