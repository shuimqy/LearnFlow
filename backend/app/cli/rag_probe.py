import json
import sys

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, MetaData, Table, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import engine
from app.services.chat_generation import generate_answer
from app.services.embeddings import EmbeddingClient
from app.services.model_api import ModelAPIError
from app.services.retrieval import RetrievedContext


def main():
    texts = [
        "向量组线性无关，当且仅当零线性组合的系数全部为零。等价地，相应齐次方程组只有零解。",
        "制作面包需要揉面、发酵和烘烤，发酵时间和烤箱温度会影响成品。",
    ]
    question = "怎么判断几个向量是否线性独立？"
    embeddings = EmbeddingClient().embed([*texts, question])
    if engine.dialect.name != "postgresql":
        raise ModelAPIError("The RAG probe requires PostgreSQL.")
    probe = Table(
        "learnflow_rag_probe",
        MetaData(),
        Column("position", Integer),
        Column("embedding", Vector(embeddings.dimensions)),
        prefixes=["TEMPORARY"],
        postgresql_on_commit="DROP",
    )
    with engine.begin() as connection:
        probe.create(connection)
        connection.execute(
            probe.insert(),
            [
                {"position": i, "embedding": vector}
                for i, vector in enumerate(embeddings.vectors[:2])
            ],
        )
        distance = probe.c.embedding.cosine_distance(embeddings.vectors[-1])
        ranked = connection.execute(select(probe.c.position, distance).order_by(distance)).all()
    if ranked[0][0] != 0:
        raise ModelAPIError("The RAG probe retrieved an unrelated source.")
    context = RetrievedContext(
        items=[
            {
                "key": "K1",
                "title": "固定测试：线性无关",
                "version": 1,
                "text": texts[0],
                "sources": [{"filename": "fixed-probe.pdf", "page_number": 1}],
            }
        ],
        mode="semantic",
        warnings=[],
    )
    response = generate_answer(question, [], context)
    if response.parsed.status != "answered" or response.parsed.citations != ["K1"]:
        raise ModelAPIError("The RAG probe did not return a grounded answer.")
    print(
        json.dumps(
            {
                "available": True,
                "embedding_model": embeddings.model,
                "dimensions": embeddings.dimensions,
                "similarity": round(1 - ranked[0][1], 4),
                "llm_model": response.model,
                "answer": response.parsed.answer,
                "citations": response.parsed.citations,
                "embedding_tokens": embeddings.total_tokens,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except ModelAPIError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except SQLAlchemyError:
        print("PostgreSQL verification failed. Check the local database service.", file=sys.stderr)
        sys.exit(1)
