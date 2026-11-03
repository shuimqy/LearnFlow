"use client";

import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Modal } from "@/components/ui";
import type { ChatImage } from "../types";

export type DraftImage = { id: string; file: File; url: string };

export function useChatImages() {
  const [images, setImages] = useState<DraftImage[]>([]);
  const current = useRef(images);
  const [error, setError] = useState("");
  function update(next: DraftImage[]) {
    for (const image of current.current) {
      if (!next.some((item) => item.id === image.id)) URL.revokeObjectURL(image.url);
    }
    current.current = next;
    setImages(next);
  }
  useEffect(
    () => () => {
      current.current.forEach((image) => URL.revokeObjectURL(image.url));
    },
    [],
  );
  function add(files: File[]) {
    setError("");
    if (current.current.length + files.length > 4) {
      setError("每条消息最多添加 4 张图片。");
      return;
    }
    if (files.some((file) => !["image/png", "image/jpeg", "image/webp"].includes(file.type))) {
      setError("请选择 JPG、PNG 或 WebP 图片。");
      return;
    }
    if (files.some((file) => file.size > 5 * 1024 * 1024)) {
      setError("每张图片不能超过 5 MB。");
      return;
    }
    update([
      ...current.current,
      ...files.map((file) => ({ id: crypto.randomUUID(), file, url: URL.createObjectURL(file) })),
    ]);
  }
  return {
    images,
    error,
    add,
    remove: (id: string) => update(current.current.filter((image) => image.id !== id)),
    clear: () => {
      update([]);
      setError("");
    },
  };
}

export function DraftImages({
  images,
  remove,
  disabled,
}: {
  images: DraftImage[];
  remove: (id: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="chat-image-drafts" aria-label="待发送图片">
      {images.map((image) => (
        <div className="chat-image-draft" key={image.id}>
          <img src={image.url} alt={image.file.name} />
          <button
            type="button"
            className="icon-button"
            disabled={disabled}
            aria-label={`移除图片 ${image.file.name}`}
            onClick={() => remove(image.id)}
          >
            <X size={14} />
          </button>
          <span title={image.file.name}>{image.file.name}</span>
        </div>
      ))}
    </div>
  );
}

export function MessageImages({ images }: { images: ChatImage[] }) {
  const [preview, setPreview] = useState<ChatImage | null>(null);
  return (
    <>
      <div className="chat-message-images">
        {images.map((image, index) => (
          <button
            type="button"
            className="chat-image-open"
            key={image.id}
            aria-label={`查看图片 ${index + 1}：${image.filename}`}
            onClick={() => setPreview(image)}
          >
            <img src={`/api/chat/images/${image.id}`} alt={image.filename} loading="lazy" />
          </button>
        ))}
      </div>
      {preview && (
        <Modal title="查看图片" wide onClose={() => setPreview(null)}>
          <div className="chat-image-preview">
            <img src={`/api/chat/images/${preview.id}`} alt={preview.filename} />
          </div>
          <a
            className="text-button"
            href={`/api/chat/images/${preview.id}`}
            target="_blank"
            rel="noreferrer"
          >
            在新标签页查看图片
          </a>
        </Modal>
      )}
    </>
  );
}
