from types import SimpleNamespace

import pymupdf
import pytest
from app.models import ExerciseAsset, WorkbookAsset
from app.schemas.document_structure import CropRegion
from app.services.exercise_layouts import crop_regions
from app.services.storage import storage_file
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_workbooks import exercises as exercises  # noqa: PLC0414
from test_workbooks import payload


def layout_input(**changes):
    return {
        "expected_version": 0,
        "question_type": "calculation",
        "difficulty": "basic",
        "knowledge_tags": ["分式计算"],
        "confirmed": True,
        "regions": [
            {"role": "question", "page_number": 1, "bbox": [0.05, 0.03, 0.95, 0.3]},
            {"role": "figure", "page_number": 2, "bbox": [0.05, 0.03, 0.95, 0.3]},
        ],
        **changes,
    }


def test_confirmed_crops_are_private_and_snapshot_survives_source_deletion(
    client, course, exercises, db_engine
):
    item = exercises["items"][0]
    base = f"/api/courses/{course['id']}/exercises/{item['draft_id']}"
    result = client.put(base + "/layout", json=layout_input())
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "confirmed"
    fresh = client.get(base).json()
    assert fresh["layout_version"] == 1 and len(fresh["assets"]) == 2
    source_asset = fresh["assets"][0]["id"]
    assert client.get(base + "/assets/" + source_asset).content.startswith(b"\x89PNG")
    assert client.put(base + "/layout", json=layout_input()).status_code == 409
    exercises["items"] = [fresh]
    request = payload(exercises)
    request["settings"]["print_mode"] = "original"
    response = client.post(exercises["base"], json=request)
    assert response.status_code == 201, response.text
    book = response.json()
    asset = book["sections"][0]["items"][0]["assets"][0]
    assert book["sections"][0]["items"][0]["asset_scope"] == "workbook"
    assert asset["id"] != source_asset
    asset_path = exercises["base"] + f"/{book['id']}/assets/{asset['id']}"
    assert client.get(asset_path).status_code == 200
    assert client.delete(f"/api/documents/{exercises['document']['id']}").status_code == 204
    assert client.get(asset_path).status_code == 200
    pdf = client.get(exercises["base"] + f"/{book['id']}/pdf?version=1")
    assert pdf.status_code == 200, pdf.text[:200] if pdf.status_code != 200 else ""
    with pymupdf.open(stream=pdf.content, filetype="pdf") as document:
        assert any(page.get_images() for page in document)
    assert client.delete(exercises["base"] + f"/{book['id']}").status_code == 204
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(WorkbookAsset.id))) == 0
        assert db.scalar(select(func.count(ExerciseAsset.id))) == 0


def test_crop_update_is_a_new_version_and_old_workbook_snapshot_stays_fixed(
    client, course, exercises
):
    base = f"/api/courses/{course['id']}/exercises/{exercises['items'][0]['draft_id']}"
    client.put(base + "/layout", json=layout_input())
    exercises["items"] = [client.get(base).json()]
    book = client.post(exercises["base"], json=payload(exercises)).json()
    old_asset = book["sections"][0]["items"][0]["assets"][0]["id"]
    client.put(
        base + "/layout",
        json=layout_input(
            expected_version=1,
            regions=[{"role": "question", "page_number": 1, "bbox": [0.1, 0.1, 0.9, 0.5]}],
        ),
    )
    path = exercises["base"] + "/" + book["id"]
    assert client.get(path).json()["sections"][0]["items"][0]["assets"][0]["id"] == old_asset
    fresh = client.get(base).json()
    edited = {**book, "expected_version": 1, "sections": [{"title": "新裁片", "items": [fresh]}]}
    result = client.put(path, json=edited)
    assert result.status_code == 200, result.text
    assert result.json()["sections"][0]["items"][0]["assets"][0]["id"] != old_asset
    assert client.get(path + "/assets/" + old_asset).status_code == 404


def test_original_export_never_silently_drops_missing_crops(client, exercises):
    request = payload(exercises)
    request["settings"]["print_mode"] = "original"
    book = client.post(exercises["base"], json=request).json()
    result = client.get(exercises["base"] + f"/{book['id']}/pdf?version=1")
    assert result.status_code == 422 and "没有已确认" in result.json()["detail"]


@pytest.mark.parametrize(
    "regions",
    [
        [{"role": "question", "page_number": 3, "bbox": [0.1, 0.1, 0.9, 0.9]}],
        [{"role": "question", "page_number": 1, "bbox": [-1, 0.1, 0.9, 0.9]}],
        [{"role": "question", "page_number": 1, "bbox": [0.9, 0.1, 0.1, 0.9]}],
        [{"role": "figure", "page_number": 1, "bbox": [0.1, 0.1, 0.9, 0.9]}],
        [],
    ],
)
def test_invalid_or_answerless_confirmation_does_not_create_assets(
    client, course, exercises, regions
):
    base = f"/api/courses/{course['id']}/exercises/{exercises['items'][0]['draft_id']}"
    result = client.put(base + "/layout", json=layout_input(regions=regions))
    assert result.status_code == 422
    assert client.get(base + "/layout").json()["version"] == 0


def test_layout_and_assets_are_isolated_by_course_and_account(client, course, exercises):
    item = exercises["items"][0]
    base = f"/api/courses/{course['id']}/exercises/{item['draft_id']}"
    client.put(base + "/layout", json=layout_input())
    asset = client.get(base).json()["assets"][0]["id"]
    other = client.post("/api/courses", json={"name": "另一课程"}).json()
    foreign = f"/api/courses/{other['id']}/exercises/{item['draft_id']}"
    assert client.get(foreign + "/layout").status_code == 404
    assert client.put(foreign + "/layout", json=layout_input()).status_code == 404
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "name": "其他用户",
            "email": "crop-private@example.com",
            "password": "safe-test-password",
        },
    )
    assert client.get(base + "/layout").status_code == 404
    assert client.get(base + "/assets/" + asset).status_code == 404


def test_rotated_page_crop_uses_the_same_coordinates_as_preview(client):
    key = "documents/rotated-fixture.pdf"
    target = storage_file(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=200, height=300)
        page.draw_rect((0, 0, 100, 150), fill=(1, 0, 0), color=(1, 0, 0))
        page.set_rotation(90)
        pdf.save(target)
    source = SimpleNamespace(storage_key=key)
    region = CropRegion(role="question", page_number=1, bbox=(0.55, 0.05, 0.95, 0.45))
    data = crop_regions(source, [region])[0]
    with pymupdf.open(stream=data, filetype="png") as pdf:
        pixmap = pdf[0].get_pixmap()
        red, green, blue = pixmap.pixel(pixmap.width // 2, pixmap.height // 2)
        assert red > 240 and green < 20 and blue < 20
