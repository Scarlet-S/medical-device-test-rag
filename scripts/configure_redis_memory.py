import json
import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
REDIS_CONTAINER = "docker-redis-1"


def read_container_password() -> str:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            REDIS_CONTAINER,
            "--format",
            "{{range .Config.Env}}{{println .}}{{end}}",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for line in result.stdout.splitlines():
        if line.startswith("REDIS_PASSWORD="):
            password = line.split("=", 1)[1]
            if password:
                return password
    raise RuntimeError(
        f"容器 {REDIS_CONTAINER} 中没有可用的 REDIS_PASSWORD"
    )


def dotenv_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def upsert_env(content: str, updates: dict[str, str]) -> str:
    lines = content.splitlines()
    remaining = dict(updates)
    output: list[str] = []

    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={dotenv_value(remaining.pop(key))}")
                continue
        output.append(line)

    if remaining:
        if output and output[-1] != "":
            output.append("")
        output.extend(
            f"{key}={dotenv_value(value)}"
            for key, value in remaining.items()
        )
    return "\n".join(output).rstrip() + "\n"


def main() -> None:
    if not ENV_PATH.exists():
        raise RuntimeError("项目根目录不存在 .env，请先复制 .env.example")

    password = read_container_password()
    original = ENV_PATH.read_text(encoding="utf-8")
    updated = upsert_env(
        original,
        {
            "REDIS_MEMORY_URL": "redis://localhost:6379/15",
            "REDIS_MEMORY_PASSWORD": password,
            "REDIS_MEMORY_TTL_SECONDS": "86400",
            "REDIS_MEMORY_MAX_MESSAGES": "20",
        },
    )
    ENV_PATH.write_text(updated, encoding="utf-8", newline="\n")
    print("Redis记忆配置已写入项目.env（密码未显示）")
    print("已配置：URL、密码、TTL、最大消息数")


if __name__ == "__main__":
    main()
