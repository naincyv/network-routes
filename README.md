# Network Route Optimization API

A small Flask API for storing servers (nodes), connecting them with latency
values (edges), and finding the lowest-latency route between two servers
using Dijkstra's algorithm. Successful route lookups are saved as history.

**Stack:** Python, Flask, Flask-SQLAlchemy, SQLite, pytest

## Setup

Create and activate a virtual environment, then install dependencies.

Windows (PowerShell):
```
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Windows (Command Prompt): `venv\Scripts\activate.bat`
Mac / Linux: `source venv/bin/activate`

## Run
```
python app.py
```
The server starts at http://127.0.0.1:5000 and creates `instance/network.db`
automatically on first run.

## Run the tests
```
pytest
```

## Endpoints
| Method | Path | Success | Errors |
|---|---|---|---|
| POST | /nodes | 201 | 400 missing or duplicate name |
## Quick start: add a node
With the server running:
```bash
curl -X POST http://127.0.0.1:5000/nodes -H "Content-Type: application/json" -d '{"name":"ServerA"}'
```
Returns `201` with `{"id": 1, "name": "ServerA"}`. List nodes with `GET /nodes`.
| POST | /edges | 201 | 400 missing fields, latency <= 0, duplicate edge, unknown node |
| POST | /routes/shortest | 200 | 404 no path, 400 unknown or missing nodes |
| GET | /routes/history | 200 | 400 bad limit or date |
| GET | /nodes, /edges | 200 | |
| DELETE | /nodes/{id}, /edges/{id} | 204 | 404 not found |

History filters: `source`, `destination`, `limit`, `date_from`, `date_to` (ISO 8601).

## Example requests
```
POST /nodes             {"name": "ServerA"}
POST /edges             {"source": "ServerA", "destination": "ServerB", "latency": 12.5}
POST /routes/shortest   {"source": "ServerA", "destination": "ServerD"}
GET  /routes/history?source=ServerA&limit=5
```

Response of `/routes/shortest`:
```json
{"total_latency": 23.4, "path": ["ServerA", "ServerB", "ServerD"]}
```

## Assumptions
- Edges are undirected: if A-B exists, B-A is treated as a duplicate and routes work in both directions.
- An edge from a node to itself is rejected.
- Asking for a route from a node to itself returns latency 0 and a one-node path.
- Only successful lookups are saved to history (a 404 "no path" is not). Newest comes first.
- History stores node names as text, so it survives deleting a node.
- Deleting a node also deletes its edges.
- Latency is rounded to 4 decimals to avoid floating-point noise.

## Database
SQLite by default (no setup needed). To use PostgreSQL, install `psycopg2-binary`
and set the `DATABASE_URL` environment variable, e.g.
`postgresql://user:password@localhost:5432/network_routes`.
