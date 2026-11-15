# Flight-data ingestion service (Go)

Receives raw telemetry from ground control stations, reduces it to a flight
summary, and forwards it to the BakımPilot API (`POST /api/ingest/flights/`,
authenticated with `X-Ingest-Token`). Standard library only.

```
POST /v1/telemetry
{"flight_id": "GS-T001-202603010800", "tail_number": "TB2-T001", "mission": "ISR",
 "samples": [{"t": "2026-03-01T08:00:00Z", "on_ground": true, "engine_temp_c": 88.1,
              "vibration_g": 0.41, "fuel_flow_lph": 11.5}, ...]}
→ 202 {"summary": {...}, "duplicate": false}
```

| Env | Default | |
|---|---|---|
| `INGEST_TOKEN` | (required) | must match the API's `INGEST_TOKEN` |
| `API_URL` | `http://api:8000/api/ingest/flights/` | |
| `LISTEN_ADDR` | `:8080` | |

Tests: `go test ./...` (or `docker build .`, which runs vet + tests).
