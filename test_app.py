import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"  # tests never touch the real DB

import pytest

from app import app, db, dijkstra


@pytest.fixture
def client():
    with app.app_context():
        db.drop_all()
        db.create_all()
    return app.test_client()


@pytest.fixture
def net(client):
    """A-B 12.5, B-D 10.9, A-D 50, B-C 5. E is not connected to anything."""
    for name in "ABCDE":
        client.post("/nodes", json={"name": name})
    for a, b, ms in [("A", "B", 12.5), ("B", "D", 10.9), ("A", "D", 50), ("B", "C", 5)]:
        client.post("/edges", json={"source": a, "destination": b, "latency": ms})
    return client


def test_dijkstra_picks_cheapest_path():
    graph = {"A": [("B", 1), ("C", 4)], "B": [("A", 1), ("C", 2)],
             "C": [("A", 4), ("B", 2)], "X": []}
    assert dijkstra(graph, "A", "C") == (3, ["A", "B", "C"])
    assert dijkstra(graph, "A", "A") == (0, ["A"])
    assert dijkstra(graph, "A", "X") is None


def test_add_node(client):
    r = client.post("/nodes", json={"name": "ServerA"})
    assert r.status_code == 201
    assert r.get_json() == {"id": 1, "name": "ServerA"}


def test_bad_nodes(client):
    assert client.post("/nodes", json={}).status_code == 400
    assert client.post("/nodes", json={"name": "   "}).status_code == 400
    assert client.post("/nodes", json={"name": 5}).status_code == 400
    assert client.post("/nodes", data="not json").status_code == 400
    client.post("/nodes", json={"name": "A"})
    assert client.post("/nodes", json={"name": "A"}).status_code == 400


def test_add_edge(client):
    client.post("/nodes", json={"name": "A"})
    client.post("/nodes", json={"name": "B"})
    r = client.post("/edges", json={"source": "A", "destination": "B", "latency": 12.5})
    assert r.status_code == 201
    assert r.get_json() == {"id": 1, "source": "A", "destination": "B", "latency": 12.5}


@pytest.mark.parametrize("body", [
    {"destination": "B", "latency": 1},                    # source missing
    {"source": "A", "destination": "E", "latency": 0},     # zero latency
    {"source": "A", "destination": "E", "latency": -3},    # negative latency
    {"source": "A", "destination": "E", "latency": "x"},   # not a number
    {"source": "A", "destination": "E", "latency": True},  # bool sneaking in as a number
    {"source": "A", "destination": "Z", "latency": 1},     # unknown node
    {"source": "A", "destination": "A", "latency": 1},     # self loop
    {"source": "A", "destination": "B", "latency": 1},     # duplicate
    {"source": "B", "destination": "A", "latency": 1},     # duplicate, reversed
])
def test_bad_edges(net, body):
    assert net.post("/edges", json=body).status_code == 400


def test_shortest_route(net):
    r = net.post("/routes/shortest", json={"source": "A", "destination": "D"})
    assert r.status_code == 200
    assert r.get_json() == {"total_latency": 23.4, "path": ["A", "B", "D"]}


def test_route_works_both_ways(net):
    r = net.post("/routes/shortest", json={"source": "D", "destination": "A"})
    assert r.get_json()["path"] == ["D", "B", "A"]


def test_same_source_and_destination(net):
    r = net.post("/routes/shortest", json={"source": "A", "destination": "A"})
    assert r.get_json() == {"total_latency": 0, "path": ["A"]}


def test_no_path_gives_404(net):
    r = net.post("/routes/shortest", json={"source": "A", "destination": "E"})
    assert r.status_code == 404
    assert "No path exists" in r.get_json()["error"]


def test_route_with_unknown_node(net):
    assert net.post("/routes/shortest", json={"source": "A", "destination": "Nope"}).status_code == 400
    assert net.post("/routes/shortest", json={}).status_code == 400


def test_history_and_filters(net):
    net.post("/routes/shortest", json={"source": "A", "destination": "D"})
    net.post("/routes/shortest", json={"source": "B", "destination": "C"})
    net.post("/routes/shortest", json={"source": "A", "destination": "E"})  # 404, not saved

    rows = net.get("/routes/history").get_json()
    assert len(rows) == 2
    assert rows[0]["source"] == "B"  # newest first
    assert set(rows[0]) == {"id", "source", "destination", "total_latency", "path", "created_at"}

    assert len(net.get("/routes/history?source=A").get_json()) == 1
    assert len(net.get("/routes/history?destination=C").get_json()) == 1
    assert len(net.get("/routes/history?limit=1").get_json()) == 1
    assert len(net.get("/routes/history?date_from=2000-01-01T00:00:00Z").get_json()) == 2
    assert len(net.get("/routes/history?date_to=2000-01-01T00:00:00Z").get_json()) == 0


def test_bad_history_params(client):
    assert client.get("/routes/history?limit=abc").status_code == 400
    assert client.get("/routes/history?limit=0").status_code == 400
    assert client.get("/routes/history?date_from=yesterday").status_code == 400


def test_delete_node_removes_its_edges_but_keeps_history(net):
    net.post("/routes/shortest", json={"source": "A", "destination": "D"})
    assert net.delete("/nodes/2").status_code == 204  # node B
    assert len(net.get("/edges").get_json()) == 1
    assert len(net.get("/routes/history").get_json()) == 1


def test_delete_edge_and_missing_ids(net):
    assert net.delete("/edges/1").status_code == 204
    assert net.delete("/edges/999").status_code == 404
    assert net.delete("/nodes/999").status_code == 404


def test_unknown_url_returns_json(client):
    r = client.get("/nope")
    assert r.status_code == 404 and "error" in r.get_json()
