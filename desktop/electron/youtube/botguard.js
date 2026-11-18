// Adapted for private DowFlow use from Liner commit 5bec3c7.
import { ipcRenderer } from "electron";
import { BotGuardClient } from "bgutils-js/botguard";
import { WebPoMinter } from "bgutils-js/webpo";

const REFRESH_MARGIN_MS = 10 * 60 * 1000;
const DEFAULT_TTL_SECONDS = 6 * 60 * 60;

export function readChallenge(raw) {
  const interpreterUrl = raw?.interpreterUrl?.privateDoNotAccessOrElseTrustedResourceUrlWrappedValue;
  const interpreterScript = raw?.interpreterJavascript?.privateDoNotAccessOrElseSafeScriptWrappedValue;
  if (!raw?.program || !raw.globalName || !(interpreterUrl || interpreterScript)) {
    throw new Error("BotGuard challenge is missing");
  }
  return {
    program: raw.program,
    globalName: raw.globalName,
    ...(interpreterUrl ? { interpreterUrl } : {}),
    ...(interpreterScript ? { interpreterScript } : {}),
  };
}

async function loadInterpreter(challenge) {
  if (challenge.interpreterScript) return challenge.interpreterScript;
  const rawUrl = challenge.interpreterUrl ?? "";
  const url = rawUrl.startsWith("//") ? `https:${rawUrl}` : rawUrl;
  return ipcRenderer.invoke("dowflow-potoken-interpreter", url);
}

export async function createMinter(challenge, generateIntegrityToken) {
  new Function(await loadInterpreter(challenge))();
  const botguard = await BotGuardClient.create({
    program: challenge.program,
    globalName: challenge.globalName,
    globalObject: globalThis,
  });
  const webPoSignalOutput = [];
  const botguardResponse = await botguard.snapshot({ webPoSignalOutput });
  const { token, ttlSeconds } = await generateIntegrityToken(botguardResponse);
  const minter = await WebPoMinter.create(
    { integrityToken: token.replace(/\+/g, "-").replace(/\//g, "_") },
    webPoSignalOutput,
  );
  const ttlMs = (ttlSeconds && ttlSeconds > 0 ? ttlSeconds : DEFAULT_TTL_SECONDS) * 1000;
  return {
    minter,
    expiresAt: Date.now() + Math.max(ttlMs - REFRESH_MARGIN_MS, 60_000),
  };
}

export function cachedMinter(create) {
  let current = null;
  let pending = null;
  return {
    get() {
      if (current && Date.now() < current.expiresAt) return Promise.resolve(current);
      pending ??= create()
        .then((entry) => {
          current = entry;
          return entry;
        })
        .finally(() => {
          pending = null;
        });
      return pending;
    },
    reset() {
      current = null;
    },
  };
}
