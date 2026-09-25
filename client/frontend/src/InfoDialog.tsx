import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

function inlineMarked(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /`([^`]*)`|\*([^*]+)\*/g;
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(re)) {
    const start = match.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    if (match[1] != null) nodes.push(<code key={key}>{match[1]}</code>);
    else nodes.push(<strong key={key}>{match[2] ?? ""}</strong>);
    key += 1;
    last = start + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes.length ? nodes : [text];
}

function PriorityBody({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push(<h3 key={key}>{inlineMarked(line.slice(3))}</h3>);
      key += 1;
      index += 1;
      continue;
    }
    if (line.startsWith("- ")) {
      const items: string[] = [];
      while (index < lines.length && lines[index].startsWith("- ")) {
        items.push(lines[index].slice(2));
        index += 1;
      }
      blocks.push(
        <ul key={key}>
          {items.map((item, itemKey) => (
            <li key={itemKey}>{inlineMarked(item)}</li>
          ))}
        </ul>
      );
      key += 1;
      continue;
    }
    if (/^\d+\. /.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\. /.test(lines[index])) {
        items.push(lines[index].replace(/^\d+\. /, ""));
        index += 1;
      }
      blocks.push(
        <ol key={key}>
          {items.map((item, itemKey) => (
            <li key={itemKey}>{inlineMarked(item)}</li>
          ))}
        </ol>
      );
      key += 1;
      continue;
    }
    const paragraph = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("## ") &&
      !lines[index].startsWith("- ") &&
      !/^\d+\. /.test(lines[index])
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(<p key={key}>{inlineMarked(paragraph.join(" "))}</p>);
    key += 1;
  }
  return <>{blocks}</>;
}

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
        {body ? <PriorityBody text={body} /> : null}
        <button type="button" className="priority-rules-close" onClick={onClose}>
          {closeLabel}
        </button>
      </div>
    </div>,
    document.body
  );
}
