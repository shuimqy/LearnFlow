import hashlib
import io
import warnings
from dataclasses import dataclass

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from app.models import ChatImage, ChatMessage, Conversation, Course

MAX_IMAGES = 4
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000


@dataclass(frozen=True)
class PreparedImage:
    filename: str
    media_type: str
    data: bytes
    width: int
    height: int
    sha256: str


def prepare_image(upload):
    if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(422, "图片仅支持 JPG、PNG 和 WebP")
    original = upload.file.read(MAX_BYTES + 1)
    if len(original) > MAX_BYTES:
        raise HTTPException(413, "每张图片不能超过 5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(original)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(422, "文件内容不是支持的图片格式")
                if source.width * source.height > MAX_PIXELS:
                    raise HTTPException(413, "图片分辨率过大，请裁剪后再发送（最多 2000 万像素）")
                if getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(422, "暂不支持动图，请发送静态图片")
                source.load()
                image = ImageOps.exif_transpose(source)
                image.thumbnail((2560, 2560))
                image = image.convert(
                    "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                )
                image.info.clear()
                output = io.BytesIO()
                image.save(output, format="PNG")
                data, media_type = output.getvalue(), "image/png"
                if len(data) > MAX_BYTES:
                    background = Image.new("RGB", image.size, "white")
                    background.paste(
                        image, mask=image.getchannel("A") if image.mode == "RGBA" else None
                    )
                    output = io.BytesIO()
                    background.save(output, format="JPEG", quality=90)
                    data, media_type = output.getvalue(), "image/jpeg"
                if len(data) > MAX_BYTES:
                    raise HTTPException(413, "图片处理后仍然过大，请裁剪后再发送")
                filename = (upload.filename or "图片").replace("\\", "/").split("/")[-1][:255]
                return PreparedImage(
                    filename,
                    media_type,
                    data,
                    image.width,
                    image.height,
                    hashlib.sha256(data).hexdigest(),
                )
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(422, "图片损坏或无法读取，请重新选择") from None


def add_images(message, images):
    message.images = [
        ChatImage(
            position=index,
            filename=image.filename,
            media_type=image.media_type,
            size=len(image.data),
            width=image.width,
            height=image.height,
            sha256=image.sha256,
            data=image.data,
        )
        for index, image in enumerate(images)
    ]


def image_rows_for(db, conversation, message, user_id):
    if message.images:
        return message.images
    earlier = db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.role == "user",
            ChatMessage.sequence < message.sequence,
            ChatMessage.images.any(),
        )
        .order_by(ChatMessage.sequence.desc())
        .limit(1)
    )
    if earlier:
        return earlier.images
    ids = conversation.context_snapshot.get("source_image_ids", [])[:MAX_IMAGES]
    if not ids:
        return []
    rows = db.scalars(
        select(ChatImage)
        .join(ChatMessage, ChatMessage.id == ChatImage.message_id)
        .join(Conversation, Conversation.id == ChatMessage.conversation_id)
        .join(Course, Course.id == Conversation.course_id)
        .where(
            ChatImage.id.in_(ids), Course.id == conversation.course_id, Course.user_id == user_id
        )
    ).all()
    by_id = {row.id: row for row in rows}
    return [by_id[image_id] for image_id in ids if image_id in by_id]


def conversation_images(db, conversation, message, user_id):
    return [image.data for image in image_rows_for(db, conversation, message, user_id)]
