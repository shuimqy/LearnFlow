import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Course
from app.services.vector_index import enqueue_course_index, index_course, index_status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "index-course", "enqueue-course"])
    parser.add_argument("--course-id", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        if not db.scalar(select(Course.id).where(Course.id == args.course_id)):
            raise SystemExit("Course not found.")
        if args.command == "status":
            print(json.dumps(index_status(db, args.course_id)))
            return
        if args.command == "enqueue-course":
            queued = enqueue_course_index(db, args.course_id, force=True)
            print(json.dumps({"queued": queued}))
            if not queued:
                raise SystemExit(1)
            return
    print(json.dumps(index_course(args.course_id)))


if __name__ == "__main__":
    main()
