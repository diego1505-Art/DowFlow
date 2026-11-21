import { HeartFill, HeartLine } from "@mingcute/react";

interface LikeIconProps {
  liked: boolean;
  size: number;
}

export function LikeMorphIcon({ liked, size }: LikeIconProps) {
  return liked ? (
    <HeartFill size={size} className="text-red-500" />
  ) : (
    <HeartLine size={size} />
  );
}
