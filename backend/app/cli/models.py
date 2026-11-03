import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Literal

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import ROOT, get_settings
from app.services.embeddings import EmbeddingClient, EmbeddingError, validate_aliyun_endpoint
from app.services.llm import LLMClient


def read_credentials(path: Path) -> tuple[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    fields = {}
    for row in rows:
        if len(row) != 2:
            raise EmbeddingError("The exported CSV must contain name/value rows.")
        name, value = row[0].strip(), row[1].strip()
        if name in fields:
            raise EmbeddingError("Duplicate fields in the exported CSV.")
        fields[name] = value
    key = fields.get("apiKey", "")
    if not re.fullmatch(r"sk-[A-Za-z0-9_.-]{16,512}", key):
        raise EmbeddingError("No supported API key was found in the CSV.")
    endpoint = validate_aliyun_endpoint(fields.get("openAiCompatible", ""))
    return key, endpoint


def validate_model(model: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", model):
        raise EmbeddingError("Invalid model identifier.")


def write_model_config(updates: dict[str, str]):
    target = ROOT / ".env"
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    for name, value in updates.items():
        pattern = re.compile(r"^" + re.escape(name) + r"\s*=.*$", re.MULTILINE)
        if len(pattern.findall(content)) > 1:
            raise EmbeddingError("Duplicate model configuration in .env; no changes made.")
        line = name + "=" + json.dumps(value)
        if pattern.search(content):
            content = pattern.sub(lambda _, replacement=line: replacement, content)
        else:
            content = content.rstrip() + "\n" + line + "\n"
    temporary = ROOT / ".env.models.tmp"
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
    get_settings.cache_clear()


def configure_embedding(path: Path, model: str, dimensions: int):
    key, endpoint = read_credentials(path)
    validate_model(model)
    write_model_config(
        {
            "EMBEDDING_API_KEY": key,
            "EMBEDDING_BASE_URL": endpoint,
            "EMBEDDING_MODEL": model,
            "EMBEDDING_DIMENSIONS": str(dimensions),
            "EMBEDDING_BATCH_SIZE": "20",
        }
    )
    print(
        json.dumps(
            {
                "configured": True,
                "model": model,
                "dimensions": dimensions,
                "credentials": "saved to ignored .env",
            }
        )
    )


def configure_llm(model: str, path: Path | None = None):
    validate_model(model)
    if path:
        key, endpoint = read_credentials(path)
    else:
        settings = get_settings()
        key = settings.embedding_api_key.get_secret_value()
        if not key or not settings.embedding_base_url:
            raise EmbeddingError(
                "Provide a credential CSV or configure the embedding credentials first."
            )
        endpoint = validate_aliyun_endpoint(settings.embedding_base_url)
    write_model_config(
        {
            "LLM_API_KEY": key,
            "LLM_BASE_URL": endpoint,
            "LLM_MODEL": model,
            "LLM_ENABLE_THINKING": "false",
            "LLM_MAX_TOKENS": "2048",
            "LLM_TIMEOUT_SECONDS": "60",
        }
    )
    print(
        json.dumps(
            {
                "configured": True,
                "model": model,
                "thinking": False,
                "credentials": "saved to ignored .env",
            }
        )
    )


class LLMProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]
    answer: str = Field(min_length=1, max_length=500)


def check_llm():
    client = LLMClient()
    plain = client.complete(
        [
            {"role": "system", "content": "你是一个学习助手，请严格遵守用户的输出要求。"},
            {"role": "user", "content": "这是一条连通性测试，请只回复 LearnFlow LLM OK。"},
        ],
        max_tokens=32,
    )
    if plain.content.strip() != "LearnFlow LLM OK":
        raise EmbeddingError("LLM responded, but the small text instruction check failed.")
    structured = client.complete(
        [
            {
                "role": "system",
                "content": "你是一个学习助手，按 JSON Schema 返回结果，不要添加额外字段。",
            },
            {"role": "user", "content": "请用一句中文解释什么是线性无关，并将 status 设为 ok。"},
        ],
        response_model=LLMProbe,
        max_tokens=192,
    )
    print(
        json.dumps(
            {
                "available": True,
                "model": plain.model,
                "thinking": client.settings.llm_enable_thinking,
                "reply": plain.content,
                "structured_output": structured.parsed.model_dump(),
                "input_tokens": plain.input_tokens + structured.input_tokens,
                "output_tokens": plain.output_tokens + structured.output_tokens,
            }
        )
    )


def check_embedding():
    texts = [
        "线性无关表示一个向量组的零线性组合只能由全部为零的系数得到。",
        "判断向量组是否线性独立，可以检查齐次方程是否只有零解。",
        "烘焙面包时需要控制发酵时间与烤箱温度。",
        "怎样判断一组向量是否线性无关？",
    ]
    result = EmbeddingClient().embed(texts)
    from app.core.database import engine

    if engine.dialect.name != "postgresql":
        raise EmbeddingError("The pgvector check requires PostgreSQL.")
    probe = Table(
        "learnflow_embedding_probe",
        MetaData(),
        Column("label", String),
        Column("embedding", Vector(result.dimensions)),
        prefixes=["TEMPORARY"],
        postgresql_on_commit="DROP",
    )
    labels = ["linear_independence", "homogeneous_equations", "bread_baking"]
    with engine.begin() as connection:
        probe.create(connection)
        connection.execute(
            probe.insert(),
            [
                {"label": label, "embedding": vector}
                for label, vector in zip(labels, result.vectors[:3], strict=True)
            ],
        )
        distance = probe.c.embedding.cosine_distance(result.vectors[3])
        ranked = connection.execute(
            select(probe.c.label, distance.label("distance")).order_by(distance)
        ).all()
    if not ranked or ranked[0].label == "bread_baking":
        raise EmbeddingError(
            "Embedding returned vectors, but the small semantic sanity check failed."
        )
    print(
        json.dumps(
            {
                "available": True,
                "model": result.model,
                "dimensions": result.dimensions,
                "vectors": len(result.vectors),
                "input_tokens": result.total_tokens,
                "postgresql_roundtrip": True,
                "ranking": [
                    {"label": row.label, "cosine_similarity": round(1 - row.distance, 4)}
                    for row in ranked
                ],
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure-embedding")
    configure.add_argument("--credentials-csv", type=Path, required=True)
    configure.add_argument("--model", default="qwen3.7-text-embedding")
    configure.add_argument(
        "--dimensions", type=int, choices=[256, 512, 768, 1024, 1536, 2048, 2560], default=1024
    )
    commands.add_parser("check-embedding")
    configure_chat = commands.add_parser("configure-llm")
    configure_chat.add_argument("--model", default="qwen3.8-flash")
    configure_chat.add_argument("--credentials-csv", type=Path)
    commands.add_parser("check-llm")
    commands.add_parser("status")
    args = parser.parse_args()
    if args.command == "configure-embedding":
        configure_embedding(args.credentials_csv, args.model, args.dimensions)
    elif args.command == "check-embedding":
        check_embedding()
    elif args.command == "configure-llm":
        configure_llm(args.model, args.credentials_csv)
    elif args.command == "check-llm":
        check_llm()
    else:
        settings = get_settings()
        print(
            json.dumps(
                {
                    "embedding_configured": bool(
                        settings.embedding_api_key.get_secret_value()
                        and settings.embedding_base_url
                        and settings.embedding_model
                    ),
                    "embedding_model": settings.embedding_model,
                    "embedding_dimensions": settings.embedding_dimensions,
                    "llm_configured": bool(
                        settings.llm_api_key.get_secret_value()
                        and settings.llm_base_url
                        and settings.llm_model
                    ),
                    "llm_model": settings.llm_model,
                    "llm_enable_thinking": settings.llm_enable_thinking,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (EmbeddingError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except SQLAlchemyError:
        print("PostgreSQL verification failed. Check the local database service.", file=sys.stderr)
        sys.exit(1)
