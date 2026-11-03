import json
import os
import subprocess
import sys
from uuid import uuid4

import pymupdf
from rq import Queue

from app.services.extraction import infer_page
from app.services.extraction_queue import redis_connection
from app.services.llm import LLMClient
from app.services.model_api import ModelAPIError


def run():
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=600, height=500)
        page.insert_text((50, 55), "Fractions and powers", fontsize=24)
        page.insert_text(
            (50, 95), "Definition: the denominator of a fraction must be nonzero.", fontsize=14
        )
        page.insert_text((50, 145), "Formula:", fontsize=16)
        page.insert_text((180, 128), "x", fontsize=24)
        page.insert_text((193, 115), "2", fontsize=14)
        page.draw_line((166, 140), (218, 140))
        page.insert_text((180, 169), "y", fontsize=24)
        page.insert_text((193, 177), "1", fontsize=14)
        page.insert_text((50, 230), "Worked example 1: Calculate 4 / 2.", fontsize=17)
        page.insert_text((50, 262), "Answer: 2. Solution: 4 divided by 2 equals 2.", fontsize=14)
        page.insert_text(
            (50, 330), "Exercise 1: Calculate 6 / 3. (No answer provided.)", fontsize=15
        )
        image = page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
        response = infer_page(page.get_text(sort=True), image, 1, LLMClient())
    parsed = response.parsed
    formulas = [formula.latex for point in parsed.knowledge for formula in point.formulas]
    examples = parsed.examples
    if not any("frac" in latex and "^" in latex and "_" in latex for latex in formulas):
        raise ModelAPIError("The synthetic fraction, superscript and subscript check failed.")
    if not any(item.kind == "worked_example" and "2" in item.answer for item in examples):
        raise ModelAPIError("The synthetic worked example check failed.")
    if not any(
        item.kind == "exercise" and not item.answer and not item.solution for item in examples
    ):
        raise ModelAPIError("The synthetic unanswered exercise check failed.")
    return {
        "model": response.model,
        "formula_check": True,
        "example_check": True,
        "unanswered_exercise_check": True,
        "knowledge_count": len(parsed.knowledge),
        "example_count": len(examples),
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }


def main():
    connection = redis_connection()
    queue = Queue("probe-" + uuid4().hex, connection=connection)
    job = queue.enqueue(
        "app.cli.extraction_probe.run",
        description="Synthetic formula and example check",
        job_timeout=180,
        result_ttl=300,
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.workers.main", "--burst", "--queue", queue.name],
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        job.refresh()
        if result.returncode or job.get_status() != "finished":
            raise ModelAPIError("The isolated queue probe failed. Check the worker output.")
        print(json.dumps({"redis_spawn_worker": True, **job.return_value()}))
    finally:
        job.delete()
        queue.delete(delete_jobs=True)


if __name__ == "__main__":
    try:
        main()
    except ModelAPIError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
