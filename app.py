import heapq
import json
import math
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///network.db")
db = SQLAlchemy(app)


# ---------------------------------------------------------------- models

class Node(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)


class Edge(db.Model):
    # One row per connection. Edges are undirected: A-B is the same as B-A.
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("node.id"), nullable=False)
    destination_id = db.Column(db.Integer, db.ForeignKey("node.id"), nullable=False)
    latency = db.Column(db.Float, nullable=False)
    source = db.relationship("Node", foreign_keys=[source_id])
    destination = db.relationship("Node", foreign_keys=[destination_id])


class RouteQuery(db.Model):
    # Names are stored as plain text so history survives if a node is deleted.
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(100), nullable=False)
    destination = db.Column(db.String(100), nullable=False)
    total_latency = db.Column(db.Float, nullable=False)
    path = db.Column(db.Text, nullable=False)  # saved as a JSON string
    created_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


# ---------------------------------------------------------------- helpers

def error(message, status=400):
    return jsonify(error=message), status


def valid_name(value):
    return isinstance(value, str) and value.strip() != ""


def valid_latency(value):
    # bool counts as a number in Python (True == 1), so rule it out first
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


def parse_date(text):
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def edge_json(e):
    return {"id": e.id, "source": e.source.name,
            "destination": e.destination.name, "latency": e.latency}


def history_json(q):
    return {"id": q.id, "source": q.source, "destination": q.destination,
            "total_latency": q.total_latency, "path": json.loads(q.path),
            "created_at": q.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")}


def dijkstra(graph, start, end):
    """graph looks like {"A": [("B", 12.5), ...]}. Returns (latency, path) or None."""
    best = {start: 0}
    came_from = {}
    heap = [(0, start)]
    while heap:
        dist, node = heapq.heappop(heap)
        if node == end:
            path = [end]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            return dist, path[::-1]
        if dist > best.get(node, math.inf):
            continue  # old entry, we already found a shorter way here
        for neighbour, latency in graph.get(node, []):
            new_dist = dist + latency
            if new_dist < best.get(neighbour, math.inf):
                best[neighbour] = new_dist
                came_from[neighbour] = node
                heapq.heappush(heap, (new_dist, neighbour))
    return None


def load_graph():
    names = {n.id: n.name for n in Node.query.all()}
    graph = {}
    for e in Edge.query.all():
        a, b = names[e.source_id], names[e.destination_id]
        graph.setdefault(a, []).append((b, e.latency))
        graph.setdefault(b, []).append((a, e.latency))
    return graph


# ---------------------------------------------------------------- nodes

@app.post("/nodes")
def add_node():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not valid_name(data.get("name")):
        return error("Name is required")
    name = data["name"].strip()

    if Node.query.filter_by(name=name).first():
        return error(f"Node '{name}' already exists")

    node = Node(name=name)
    db.session.add(node)
    db.session.commit()
    return jsonify(id=node.id, name=node.name), 201


@app.get("/nodes")
def list_nodes():
    return jsonify([{"id": n.id, "name": n.name} for n in Node.query.order_by(Node.id)])


@app.delete("/nodes/<int:node_id>")
def delete_node(node_id):
    node = db.session.get(Node, node_id)
    if node is None:
        return error("Node not found", 404)
    # remove the edges that touch this node first
    Edge.query.filter((Edge.source_id == node_id) | (Edge.destination_id == node_id)).delete()
    db.session.delete(node)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------- edges

@app.post("/edges")
def add_edge():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Request body must be JSON")

    src_name, dst_name, latency = data.get("source"), data.get("destination"), data.get("latency")
    if not valid_name(src_name) or not valid_name(dst_name):
        return error("Source and destination are required")
    if not valid_latency(latency):
        return error("Latency must be a number greater than 0")
    src_name, dst_name = src_name.strip(), dst_name.strip()
    if src_name == dst_name:
        return error("Source and destination must be different")

    src = Node.query.filter_by(name=src_name).first()
    dst = Node.query.filter_by(name=dst_name).first()
    if not src or not dst:
        return error("Source or destination node not found")

    # A-B and B-A are the same connection, so check both directions
    exists = Edge.query.filter(
        ((Edge.source_id == src.id) & (Edge.destination_id == dst.id)) |
        ((Edge.source_id == dst.id) & (Edge.destination_id == src.id))
    ).first()
    if exists:
        return error("Edge already exists")

    edge = Edge(source_id=src.id, destination_id=dst.id, latency=latency)
    db.session.add(edge)
    db.session.commit()
    return jsonify(edge_json(edge)), 201


@app.get("/edges")
def list_edges():
    return jsonify([edge_json(e) for e in Edge.query.order_by(Edge.id)])


@app.delete("/edges/<int:edge_id>")
def delete_edge(edge_id):
    edge = db.session.get(Edge, edge_id)
    if edge is None:
        return error("Edge not found", 404)
    db.session.delete(edge)
    db.session.commit()
    return "", 204


# ---------------------------------------------------------------- routes

@app.post("/routes/shortest")
def shortest_route():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error("Request body must be JSON")

    start, end = data.get("source"), data.get("destination")
    if not valid_name(start) or not valid_name(end):
        return error("Source and destination are required")
    start, end = start.strip(), end.strip()

    existing = {n.name for n in Node.query.filter(Node.name.in_([start, end]))}
    if start not in existing or end not in existing:
        return error("Source or destination node does not exist")

    result = dijkstra(load_graph(), start, end)
    if result is None:
        return error(f"No path exists between {start} and {end}", 404)

    total, path = result
    total = round(total, 4)  # avoids 23.400000000000002

    db.session.add(RouteQuery(source=start, destination=end,
                              total_latency=total, path=json.dumps(path)))
    db.session.commit()
    return jsonify(total_latency=total, path=path)


@app.get("/routes/history")
def route_history():
    query = RouteQuery.query

    if request.args.get("source"):
        query = query.filter_by(source=request.args["source"])
    if request.args.get("destination"):
        query = query.filter_by(destination=request.args["destination"])

    date_from, date_to = request.args.get("date_from"), request.args.get("date_to")
    if date_from:
        d = parse_date(date_from)
        if d is None:
            return error("date_from must be an ISO 8601 date, e.g. 2026-02-20T14:00:00Z")
        query = query.filter(RouteQuery.created_at >= d)
    if date_to:
        d = parse_date(date_to)
        if d is None:
            return error("date_to must be an ISO 8601 date, e.g. 2026-02-20T14:00:00Z")
        query = query.filter(RouteQuery.created_at <= d)

    query = query.order_by(RouteQuery.created_at.desc(), RouteQuery.id.desc())

    limit = request.args.get("limit")
    if limit is not None:
        if not limit.isdigit() or int(limit) < 1:
            return error("limit must be a positive whole number")
        query = query.limit(int(limit))

    return jsonify([history_json(q) for q in query])


# ---------------------------------------------------------------- errors

@app.errorhandler(404)
def not_found(e):
    return error("Resource not found", 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return error("Method not allowed", 405)


# ---------------------------------------------------------------- run

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
