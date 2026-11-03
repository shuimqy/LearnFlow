import argparse
import json

from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import Document, ExtractionDraft, PageExtraction
from app.services.extraction import import_existing_document


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending")
    importer = commands.add_parser("import-existing")
    importer.add_argument("--document-id", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.command == "pending":
            rows = db.execute(
                select(Document.id, Document.filename, func.count(ExtractionDraft.id))
                .join(PageExtraction, PageExtraction.document_id == Document.id)
                .join(ExtractionDraft, ExtractionDraft.extraction_id == PageExtraction.id)
                .where(ExtractionDraft.status == "pending")
                .group_by(Document.id, Document.filename)
            ).all()
            print(
                json.dumps(
                    [
                        {"document_id": document_id, "filename": filename, "pending": count}
                        for document_id, filename, count in rows
                    ],
                    ensure_ascii=False,
                )
            )
        else:
            print(json.dumps(import_existing_document(db, args.document_id)))


if __name__ == "__main__":
    try:
        main()
    except HTTPException as exc:
        raise SystemExit(exc.detail) from None
