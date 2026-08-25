import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.memory import RedisConversationMemory
from app.models import EvaluationJob, EvaluationRunRequest
from app.observability import EVALUATION_JOBS, LOGGER


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = (PROJECT_ROOT / "evaluation" / "results").resolve()
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_batch_eval.py"
AGENT_RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_agent_eval.py"

DATASETS = {
    "baseline": (
        PROJECT_ROOT
        / "evaluation"
        / "baseline"
        / "医疗器械软件测试知识库_评测工作簿_v1.xlsx"
    ),
    "holdout": (
        PROJECT_ROOT
        / "evaluation"
        / "holdout"
        / "医疗器械软件测试知识库_独立留出测试工作簿_v1.xlsx"
    ),
    "expansion": (
        PROJECT_ROOT
        / "evaluation"
        / "expansion"
        / "医疗器械软件测试知识库_官方扩充评测工作簿_v1.xlsx"
    ),
    "practice": (
        PROJECT_ROOT
        / "evaluation"
        / "practice"
        / "practice_documents_evaluation_v1.json"
    ),
    "blind": (
        PROJECT_ROOT
        / "evaluation"
        / "blind"
        / "final_blind_evaluation_v1.json"
    ),
    "agent": (
        PROJECT_ROOT
        / "evaluation"
        / "agent"
        / "agent_evaluation_v1.json"
    ),
}

DATASET_LIMITS = {
    "baseline": 50,
    "holdout": 30,
    "expansion": 100,
    "practice": 24,
    "blind": 30,
    "agent": 30,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvaluationJobManager:
    def __init__(self, memory: RedisConversationMemory) -> None:
        self.redis = memory.client
        self.ttl_seconds = int(
            os.getenv("EVALUATION_JOB_TTL_SECONDS", "604800")
        )
        self.timeout_seconds = int(
            os.getenv("EVALUATION_JOB_TIMEOUT_SECONDS", "7200")
        )
        self.semaphore = asyncio.Semaphore(1)
        self.tasks: set[asyncio.Task] = set()

    def key(self, job_id: str) -> str:
        return f"mdtr:evaluation:v1:{job_id}"

    async def save(self, job: EvaluationJob) -> None:
        await self.redis.set(
            self.key(job.job_id),
            job.model_dump_json(),
            ex=self.ttl_seconds,
        )

    async def get(self, job_id: str) -> EvaluationJob | None:
        raw = await self.redis.get(self.key(job_id))
        return EvaluationJob.model_validate_json(raw) if raw else None

    async def start(self, request: EvaluationRunRequest) -> EvaluationJob:
        max_cases = DATASET_LIMITS[request.dataset]
        requested_cases = len(request.question_ids) or request.limit
        if requested_cases > max_cases:
            raise ValueError(
                f"{request.dataset}题集最多包含{max_cases}题"
            )

        dataset_path = DATASETS[request.dataset]
        if not dataset_path.is_file():
            raise FileNotFoundError(f"找不到登记题集：{dataset_path}")

        job = EvaluationJob(
            job_id=f"eval-{uuid4().hex}",
            status="queued",
            request=request,
            created_at=utc_now(),
        )
        await self.save(job)
        task = asyncio.create_task(self._run(job.job_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    def build_command(self, job: EvaluationJob) -> list[str]:
        dataset_path = DATASETS[job.request.dataset]
        label = job.request.label or (
            f"api_{job.request.dataset}_{job.job_id[-8:]}"
        )
        if job.request.dataset == "agent":
            command = [
                sys.executable,
                str(AGENT_RUNNER_PATH),
                "--limit",
                str(len(job.request.question_ids) or job.request.limit),
                "--dataset",
                str(dataset_path),
                "--label",
                label,
            ]
        else:
            command = [
                sys.executable,
                str(RUNNER_PATH),
                "--limit",
                str(len(job.request.question_ids) or job.request.limit),
                "--workbook",
                str(dataset_path),
                "--label",
                label,
            ]
        if job.request.question_ids:
            command.extend(
                [
                    "--case-ids" if job.request.dataset == "agent" else "--question-ids",
                    ",".join(job.request.question_ids),
                ]
            )
        return command

    async def _run(self, job_id: str) -> None:
        async with self.semaphore:
            job = await self.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = utc_now()
            await self.save(job)

            process = None
            try:
                environment = os.environ.copy()
                environment["PYTHONIOENCODING"] = "utf-8"
                process = await asyncio.create_subprocess_exec(
                    *self.build_command(job),
                    cwd=str(PROJECT_ROOT),
                    env=environment,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
                output = stdout.decode("utf-8", errors="replace")
                job.log_tail = output[-12000:]

                if process.returncode != 0:
                    raise RuntimeError(
                        f"评测进程退出码：{process.returncode}"
                    )

                json_match = re.search(r"JSON结果：(.+)", output)
                csv_match = re.search(r"CSV结果：(.+)", output)
                if not json_match or not csv_match:
                    raise RuntimeError("评测输出未包含结果文件路径")

                json_path = Path(json_match.group(1).strip()).resolve()
                csv_path = Path(csv_match.group(1).strip()).resolve()
                if (
                    not json_path.is_relative_to(RESULTS_DIR)
                    or not csv_path.is_relative_to(RESULTS_DIR)
                ):
                    raise RuntimeError("评测结果路径超出允许目录")

                payload = json.loads(json_path.read_text(encoding="utf-8"))
                job.summary = payload.get("summary", {})
                job.json_result = str(json_path)
                job.csv_result = str(csv_path)
                job.status = "succeeded"
            except asyncio.TimeoutError:
                if process is not None:
                    process.kill()
                    await process.wait()
                job.status = "failed"
                job.error = (
                    f"评测任务超过{self.timeout_seconds}秒，已终止"
                )
            except asyncio.CancelledError:
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.wait()
                job.status = "cancelled"
                job.error = "评测任务被取消"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.finished_at = utc_now()
                await self.save(job)
                EVALUATION_JOBS.labels(job.status).inc()
                LOGGER.info(
                    "evaluation_job_finished",
                    extra={
                        "event": "evaluation_job",
                        "job_id": job.job_id,
                        "status_code": job.status,
                    },
                )

    async def load_result(self, job: EvaluationJob) -> dict:
        if job.status != "succeeded" or not job.json_result:
            raise ValueError("评测任务尚未产生可用结果")
        path = Path(job.json_result).resolve()
        if not path.is_relative_to(RESULTS_DIR):
            raise ValueError("评测结果路径超出允许目录")
        return json.loads(path.read_text(encoding="utf-8"))
