def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert client.get("/api/v1/health").status_code == 200


def test_world_builds(world):
    assert world.estudiante.id
