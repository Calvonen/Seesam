# Seesam

Seesam is a small containerized Python service. The core container exposes a JSON
health endpoint that can be used to verify the development environment.

## Development

Start the service with Docker Compose:

```sh
docker compose up seesam-core
```

The service listens on port `8000` and exposes:

- `GET /` - basic service status
- `GET /health` - health-check response

Run the test suite locally with:

```sh
python -m pytest
```
