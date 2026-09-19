import React, { useMemo } from "react";

interface MarkdownViewerProps {
  content: string;
  className?: string;
}

/**
 * Lightweight, zero-dependency Markdown renderer for resume snapshots.
 * Renders headers, lists, dividers, links, bold, italic, and code blocks
 * with clean Tailwind typography.
 */
export function MarkdownViewer({ content, className = "" }: MarkdownViewerProps) {
  const elements = useMemo(() => {
    if (!content) return [];
    const lines = content.split("\n");
    const blocks: React.ReactNode[] = [];
    let currentList: string[] = [];

    function flushList(keyPrefix: number) {
      if (currentList.length > 0) {
        blocks.push(
          <ul
            key={`ul-${keyPrefix}`}
            className="my-2 space-y-1 list-disc pl-5 text-xs text-foreground/90 leading-relaxed"
          >
            {currentList.map((item, idx) => (
              <li key={`li-${keyPrefix}-${idx}`} className="pl-0.5">
                {renderInline(item)}
              </li>
            ))}
          </ul>,
        );
        currentList = [];
      }
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      if (!trimmed) {
        flushList(i);
        continue;
      }

      if (trimmed.startsWith("# ")) {
        flushList(i);
        blocks.push(
          <h1
            key={`h1-${i}`}
            className="text-lg font-bold tracking-tight text-foreground mt-2 mb-1"
          >
            {renderInline(trimmed.slice(2))}
          </h1>,
        );
      } else if (trimmed.startsWith("## ")) {
        flushList(i);
        blocks.push(
          <h2
            key={`h2-${i}`}
            className="text-xs font-bold uppercase tracking-wider text-muted-foreground border-b border-border pb-1 mt-4 mb-2"
          >
            {renderInline(trimmed.slice(3))}
          </h2>,
        );
      } else if (trimmed.startsWith("### ")) {
        flushList(i);
        blocks.push(
          <h3 key={`h3-${i}`} className="text-xs font-semibold text-foreground mt-3 mb-0.5">
            {renderInline(trimmed.slice(4))}
          </h3>,
        );
      } else if (trimmed.startsWith("#### ")) {
        flushList(i);
        blocks.push(
          <h4 key={`h4-${i}`} className="text-[11px] font-semibold text-foreground/90 mt-2 mb-0.5">
            {renderInline(trimmed.slice(5))}
          </h4>,
        );
      } else if (trimmed === "---" || trimmed === "***" || trimmed === "___") {
        flushList(i);
        blocks.push(<hr key={`hr-${i}`} className="my-2.5 border-border/70" />);
      } else if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        currentList.push(trimmed.slice(2));
      } else {
        flushList(i);
        blocks.push(
          <p key={`p-${i}`} className="text-xs text-foreground/85 leading-relaxed my-1">
            {renderInline(trimmed)}
          </p>,
        );
      }
    }
    flushList(lines.length);
    return blocks;
  }, [content]);

  return <div className={`select-text text-foreground font-sans ${className}`}>{elements}</div>;
}

function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    // Link: [label](url)
    const linkMatch = remaining.match(/^\[(.*?)\]\((.*?)\)/);
    if (linkMatch) {
      parts.push(
        <a
          key={`link-${key++}`}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline font-medium inline-flex items-center gap-0.5"
        >
          {linkMatch[1]}
        </a>,
      );
      remaining = remaining.slice(linkMatch[0].length);
      continue;
    }

    // Bold: **text**
    const boldMatch = remaining.match(/^\*\*(.*?)\*\*/);
    if (boldMatch) {
      parts.push(
        <strong key={`bold-${key++}`} className="font-semibold text-foreground">
          {renderInline(boldMatch[1])}
        </strong>,
      );
      remaining = remaining.slice(boldMatch[0].length);
      continue;
    }

    // Code: `text`
    const codeMatch = remaining.match(/^`([^`]+)`/);
    if (codeMatch) {
      parts.push(
        <code
          key={`code-${key++}`}
          className="px-1 py-0.5 rounded bg-surface font-mono text-[11px] text-foreground border border-border"
        >
          {codeMatch[1]}
        </code>,
      );
      remaining = remaining.slice(codeMatch[0].length);
      continue;
    }

    // Italic: *text*
    const italicMatch = remaining.match(/^\*([^*]+)\*/);
    if (italicMatch) {
      parts.push(
        <em key={`italic-${key++}`} className="italic text-muted-foreground">
          {renderInline(italicMatch[1])}
        </em>,
      );
      remaining = remaining.slice(italicMatch[0].length);
      continue;
    }

    // Plain text until next markdown delimiter
    const nextSpecial = remaining.search(/(\[|\*\*|\*|`)/);
    if (nextSpecial === -1) {
      parts.push(remaining);
      break;
    } else if (nextSpecial > 0) {
      parts.push(remaining.slice(0, nextSpecial));
      remaining = remaining.slice(nextSpecial);
    } else {
      parts.push(remaining[0]);
      remaining = remaining.slice(1);
    }
  }

  return parts;
}
