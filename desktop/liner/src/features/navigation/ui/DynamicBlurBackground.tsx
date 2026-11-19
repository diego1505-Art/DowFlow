import { memo, useState } from "react";
import PageCoverBackdrop from "./PageCoverBackdrop";
import { useActiveBackgroundCover } from "../hooks/useActiveBackgroundCover";

export interface DynamicBlurBackgroundProps {
  isDark?: boolean;
}

interface ShownCover {
  src: string | null;
  crossOrigin?: "anonymous";
}

export function DynamicBlurBackground({
  isDark = true,
}: DynamicBlurBackgroundProps) {
  const { cover, pageBackdropOptions } = useActiveBackgroundCover();
  const [shown, setShown] = useState<ShownCover | null>(null);

  if (cover.kind === "ready") {
    if (shown?.src !== cover.src || shown.crossOrigin !== cover.crossOrigin) {
      setShown({ src: cover.src, crossOrigin: cover.crossOrigin });
    }
  } else if (cover.kind === "none" && shown && shown.src !== null) {
    setShown({ src: null });
  }

  if (!shown) return null;

  return (
    <PageCoverBackdrop
      coverSrc={shown.src}
      coverCrossOrigin={shown.crossOrigin}
      isDark={isDark}
      blur={pageBackdropOptions?.blur}
      dim={pageBackdropOptions?.dim}
    />
  );
}

export default memo(DynamicBlurBackground);
