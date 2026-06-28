from core.main import health_payload


def test_health_payload_identifies_service():
    payload = health_payload()

    assert payload["service"] == "seesam-core"
    assert payload["status"] == "ok"
    assert "data_dir" in payload
