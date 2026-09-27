"""单位管理接口测试"""


def test_seed_units_listed(client):
    data = client.get("/api/units").json()
    assert data["total"] == 5
    codes = {u["unit_code"] for u in data["items"]}
    assert "1101010001" in codes


def test_create_unit(client):
    resp = client.post("/api/units", json={"unit_code": "6600000001", "unit_name": "测试单位"})
    assert resp.status_code == 201
    assert resp.json()["unit_code"] == "6600000001"
    assert client.get("/api/units").json()["total"] == 6


def test_create_duplicate_unit_rejected(client):
    resp = client.post("/api/units", json={"unit_code": "1101010001", "unit_name": "重复单位"})
    assert resp.status_code == 409


def test_delete_unit(client):
    data = client.get("/api/units").json()
    uid = data["items"][0]["id"]
    assert client.delete(f"/api/units/{uid}").status_code == 200
    assert client.get("/api/units").json()["total"] == 4
