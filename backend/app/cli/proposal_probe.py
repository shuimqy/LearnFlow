import json

from app.services.model_api import ModelAPIError
from app.services.proposal_review import review_proposal


def main():
    current = {
        "title": "线性无关的定义",
        "summary": "向量组的线性关系",
        "content": "只要向量组中的每个向量都非零，该向量组就一定线性无关。",
    }
    proposed = {
        "title": current["title"],
        "summary": current["summary"],
        "content": "向量组线性无关，当且仅当它的零线性组合只能由全部为零的系数得到。",
    }
    response = review_proposal(
        current, proposed, "原结论缺少判断条件，请按线性无关的定义修正。", [], [], False
    )
    review = response.parsed
    if review.verdict not in {"approve", "revise"} or not review.content.strip():
        raise ModelAPIError("The synthetic definition correction was not accepted.")
    print(
        json.dumps(
            {
                "available": True,
                "model": response.model,
                "verdict": review.verdict,
                "basis": review.basis,
                "opinion": review.opinion,
                "revision_generated": bool(review.content),
                "database_written": False,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except ModelAPIError as exc:
        raise SystemExit(str(exc)) from None
