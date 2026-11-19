import { motion } from "framer-motion";
import LocalFilesCover from "./LocalFilesCover";

interface LocalDropStackProps {
  fileCount: number;
}

const FAN = [
  { rotate: -12, x: -34, y: 10, opacity: 0.55 },
  { rotate: 11, x: 34, y: 8, opacity: 0.7 },
];

export default function LocalDropStack({ fileCount }: LocalDropStackProps) {
  const fanned = FAN.slice(0, Math.max(0, Math.min(fileCount, 3) - 1));

  return (
    <div className="relative h-[132px] w-[132px]">
      {fanned.map((card, index) => (
        <motion.div
          key={index}
          initial={{ rotate: 0, x: 0, y: 0, opacity: 0 }}
          animate={card}
          transition={{
            type: "spring",
            stiffness: 260,
            damping: 22,
            delay: 0.04,
          }}
          className="absolute inset-0 overflow-hidden rounded-[16px] shadow-xl"
        >
          <LocalFilesCover />
        </motion.div>
      ))}
      <motion.div
        initial={{ scale: 0.82, rotate: -6, y: 14 }}
        animate={{ scale: 1, rotate: 0, y: [0, -6, 0] }}
        transition={{
          scale: { type: "spring", stiffness: 320, damping: 20 },
          rotate: { type: "spring", stiffness: 320, damping: 20 },
          y: { duration: 2.4, repeat: Infinity, ease: "easeInOut" },
        }}
        className="absolute inset-0 overflow-hidden rounded-[16px] shadow-2xl ring-1 ring-white/15"
      >
        <LocalFilesCover />
      </motion.div>
    </div>
  );
}
