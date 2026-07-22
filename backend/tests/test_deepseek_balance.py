import json

from app.config import Settings
from app.services.deepseek_balance import DeepSeekBalanceService


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "is_available": True,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "18.50",
                    "granted_balance": "3.50",
                    "topped_up_balance": "15.00",
                }
            ],
        }


def test_balance_is_fetched_on_backend_and_cached(monkeypatch, tmp_path):
    settings = Settings(
        workspace_root=tmp_path,
        deepseek_api_key="server-only-secret",
        deepseek_base_url="https://api.deepseek.com",
    )
    service = DeepSeekBalanceService(settings)
    requests = []

    def fake_get(url, *, headers, timeout):
        requests.append((url, headers, timeout))
        return FakeResponse()

    monkeypatch.setattr("httpx.get", fake_get)

    first = service.current(refresh=True)
    second = service.current()

    assert first == second
    assert first["available"] is True
    assert first["infos"][0]["total_balance"] == "18.50"
    assert len(requests) == 1
    url, headers, timeout = requests[0]
    assert url == "https://api.deepseek.com/user/balance"
    assert headers["Authorization"] == "Bearer server-only-secret"
    assert timeout == 15
    assert "server-only-secret" not in json.dumps(first)
