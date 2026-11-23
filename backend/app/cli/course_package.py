import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.personal import PERSONAL_USER_ID
from app.services.course_package import export_course_package, validate_course_package


def main():
    parser = argparse.ArgumentParser(description="Export and verify LearnFlow course packages.")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--course-id", required=True)
    export.add_argument("--owner-id")
    export.add_argument("path", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("path", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "verify":
            report = validate_course_package(args.path)
        else:
            owner_id = args.owner_id
            if owner_id is None and get_settings().app_mode == "personal":
                owner_id = PERSONAL_USER_ID
            if owner_id is None:
                parser.error("Specify --owner-id in multiuser mode.")
            if args.path.exists():
                raise ValueError("The output path already exists")
            args.path.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix="course-export-", dir=args.path.parent) as folder:
                staging = Path(folder) / "course.zip"
                with SessionLocal() as db:
                    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                    export_course_package(db, args.course_id, owner_id, staging)
                report = validate_course_package(staging)
                staging.rename(args.path)
    except SQLAlchemyError:
        raise SystemExit("Course package error: Could not read the course database.") from None
    except (OSError, ValueError, KeyError, BadZipFile) as exc:
        raise SystemExit(f"Course package error: {exc}") from None

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
