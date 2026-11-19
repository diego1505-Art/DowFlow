import { memo, useMemo } from "react";
import { findHighlightRanges } from "@/shared/utils/trackSearch";

interface HighlightedTextProps {
  text: string;
  query?: string;
}

/** Text with the parts matching `query` softly marked (search results). */
function HighlightedText({ text, query }: HighlightedTextProps) {
  const ranges = useMemo(
    () => (query ? findHighlightRanges(text, query) : []),
    [text, query],
  );
  if (ranges.length === 0) return <>{text}</>;

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  ranges.forEach(([start, end], i) => {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark
        key={i}
        className="rounded-[3px] bg-text-primary/[0.16] text-inherit [box-decoration-break:clone]"
      >
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  });
  if (cursor < text.length) parts.push(text.slice(cursor));
  return <>{parts}</>;
}

export default memo(HighlightedText);
