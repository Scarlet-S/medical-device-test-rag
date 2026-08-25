from scripts.configure_redis_memory import upsert_env


def test_upsert_env_preserves_existing_values_and_hides_password():
    original = "RAGFLOW_BASE_URL=http://localhost:9380\nREDIS_MEMORY_URL=old\n"

    result = upsert_env(
        original,
        {
            "REDIS_MEMORY_URL": "redis://localhost:6379/15",
            "REDIS_MEMORY_PASSWORD": "secret-value",
        },
    )

    assert "RAGFLOW_BASE_URL=http://localhost:9380" in result
    assert 'REDIS_MEMORY_URL="redis://localhost:6379/15"' in result
    assert "REDIS_MEMORY_PASSWORD=secret-value" in result
    assert result.count("REDIS_MEMORY_URL=") == 1
