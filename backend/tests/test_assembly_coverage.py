from app.services.workbook_assembly import select_candidates


def test_coverage_is_not_limited_to_first_type_bucket():
    rows = [
        {
            "draft_id": "a",
            "question": "question a",
            "question_type": "choice",
            "difficulty": "basic",
            "knowledge_tags": ["向量"],
            "document_id": "doc",
        },
        {
            "draft_id": "b",
            "question": "question b",
            "question_type": "choice",
            "difficulty": "basic",
            "knowledge_tags": ["向量"],
            "document_id": "doc",
        },
        {
            "draft_id": "c",
            "question": "question c",
            "question_type": "proof",
            "difficulty": "advanced",
            "knowledge_tags": ["矩阵"],
            "document_id": "doc",
        },
    ]
    assert {item["draft_id"] for item in select_candidates(rows, 2, {}, {})} == {"a", "c"}


def test_different_figure_questions_are_not_deduplicated_by_same_stem():
    first = {
        "draft_id": "a",
        "question": "如图求面积",
        "question_type": "calculation",
        "difficulty": "basic",
        "knowledge_tags": ["面积"],
        "document_id": "doc",
    }
    second = {**first, "draft_id": "b"}
    assert len(select_candidates([first, second], 2, {}, {})) == 2
