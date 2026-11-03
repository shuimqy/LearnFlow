"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle, X } from "lucide-react";

export function Spinner({ label = "正在载入" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle size={20} className="spin" />
      <span>{label}</span>
    </div>
  );
}

export function Notice({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="notice" role="alert">
      <span>{message}</span>
      {retry && (
        <button className="text-button" onClick={retry}>
          重试
        </button>
      )}
    </div>
  );
}

export function Modal({
  title,
  description,
  children,
  onClose,
  busy = false,
  wide = false,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  onClose: () => void;
  busy?: boolean;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? "modal-wide" : ""}`}
      aria-labelledby="modal-title"
      aria-describedby={description ? "modal-description" : undefined}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal-content">
        <button
          className="icon-button modal-close"
          aria-label="关闭"
          onClick={onClose}
          disabled={busy}
        >
          <X size={18} />
        </button>
        <h2 id="modal-title">{title}</h2>
        {description && (
          <p id="modal-description" className="muted">
            {description}
          </p>
        )}
        {children}
      </div>
    </dialog>
  );
}
