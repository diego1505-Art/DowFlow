const WEAK_GPU =
  /swiftshader|llvmpipe|softpipe|software|microsoft basic|intel\(r\) hd graphics|intel\(r\) uhd graphics 6\d\d|mali-[gt]\d|adreno \(tm\) [1-5]/i;

let cachedWeak: boolean | null = null;

function readNumber(source: object, key: string): number | undefined {
  const value: unknown = Reflect.get(source, key);
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function gpuRenderer(): string {
  try {
    const gl = document.createElement("canvas").getContext("webgl");
    if (!gl) return "software";
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = info
      ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL)
      : gl.getParameter(gl.RENDERER);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return typeof renderer === "string" ? renderer : "";
  } catch {
    return "";
  }
}

export function isWeakDevice(): boolean {
  if (cachedWeak !== null) return cachedWeak;
  if (typeof navigator === "undefined") return false;
  const cores = readNumber(navigator, "hardwareConcurrency") ?? 8;
  const memoryGb = readNumber(navigator, "deviceMemory") ?? 8;
  cachedWeak = cores <= 4 || memoryGb <= 4 || WEAK_GPU.test(gpuRenderer());
  return cachedWeak;
}
