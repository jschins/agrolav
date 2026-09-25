import { useEffect } from "react";
import { createPortal } from "react-dom";

export function PriorityRulesDialog({
  title,
  body,
  closeLabel,
  onClose,
}: {
  title: string;
  body: string;
  closeLabel: string;
  onClose: () => void;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="priority-rules-overlay" onClick={onClose}>
      <div
        className="priority-rules-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="priority-rules-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="priority-rules-title">{title}</h2>
        {body ? <div className="lang-html" dangerouslySetInnerHTML={{ __html: body }} /> : null}
        <button type="button" className="priority-rules-close" onClick={onClose}>
          {closeLabel}
        </button>
      </div>
    </div>,
    document.body
  );
}
