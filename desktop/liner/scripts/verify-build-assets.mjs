import { existsSync, readFileSync } from "node:fs";

const { build } = JSON.parse(readFileSync("package.json", "utf8"));
const required = [build.linux?.icon, build.win?.icon, build.mac?.icon].filter(
  (path) => typeof path === "string",
);

const missing = required.filter((path) => !existsSync(path));
if (missing.length > 0) {
  console.error(
    `Missing icons referenced by the build config: ${missing.join(", ")}`,
  );
  process.exit(1);
}
console.log(`Build icons present: ${required.join(", ")}`);
