import localFilesCover from "@/assets/local-files-cover.svg";
import { cn } from "@/shared/lib";

interface LocalFilesCoverProps {
  className?: string;
}

export default function LocalFilesCover({ className }: LocalFilesCoverProps) {
  return (
    <img
      src={localFilesCover}
      alt=""
      draggable={false}
      className={cn("h-full w-full select-none object-cover", className)}
    />
  );
}
