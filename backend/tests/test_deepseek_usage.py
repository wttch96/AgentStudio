from app.config import Settings
from app.services.deepseek_usage import DeepSeekUsageService
from app.storage.sqlite_store import SQLiteStore


class FakeUsage:
    def model_dump(self):
        return {
            "prompt_tokens": 300,
            "prompt_cache_hit_tokens": 100,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens": 300,
            "total_tokens": 600,
        }


class FakeResponse:
    model = "deepseek-test"
    usage = FakeUsage()


def test_usage_is_persisted_and_cost_is_estimated_locally(tmp_path):
    settings = Settings(
        instance_dir=tmp_path,
        deepseek_cache_hit_price=1,
        deepseek_cache_miss_price=2,
        deepseek_output_price=3,
    )
    service = DeepSeekUsageService(settings, SQLiteStore(settings.database_path))

    service.record(FakeResponse(), phase="planning", run_id="run-1")
    summary = service.summary()

    assert summary["local"] is True
    assert summary["estimated"] is True
    assert summary["all_time"]["requests"] == 1
    assert summary["all_time"]["cache_hit_tokens"] == 100
    assert summary["all_time"]["cache_miss_tokens"] == 200
    assert summary["all_time"]["completion_tokens"] == 300
    assert summary["all_time"]["total_tokens"] == 600
    assert summary["all_time"]["estimated_cost_usd"] == "0.00140000"
