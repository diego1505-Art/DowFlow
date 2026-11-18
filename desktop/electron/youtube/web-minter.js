// Adapted for private DowFlow use from Liner commit 5bec3c7.
import { buildURL, GOOG_API_KEY } from "bgutils-js/utils";
import { cachedMinter, createMinter, readChallenge } from "./botguard.js";

const REQUEST_KEY = "O43z0dpjhgX20SCx4KAo";
const WEB_CLIENT_VERSION = "2.20250925.01.00";

async function fetchWebChallenge() {
  const response = await fetch("/youtubei/v1/att/get?prettyPrint=false", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      context: {
        client: {
          clientName: "WEB",
          clientVersion: WEB_CLIENT_VERSION,
          hl: "en",
          gl: "US",
        },
      },
      engagementType: "ENGAGEMENT_TYPE_UNBOUND",
    }),
  });
  if (!response.ok) throw new Error(`YouTube att/get returned ${response.status}`);
  return readChallenge(await response.json().then((body) => body.bgChallenge));
}

async function generateWebIntegrityToken(botguardResponse) {
  const response = await fetch(buildURL("GenerateIT", true), {
    method: "POST",
    headers: {
      "content-type": "application/json+protobuf",
      "x-goog-api-key": GOOG_API_KEY,
      "x-user-agent": "grpc-web-javascript/0.1",
    },
    body: JSON.stringify([REQUEST_KEY, botguardResponse]),
  });
  if (!response.ok) throw new Error(`GenerateIT returned ${response.status}`);
  const [token, ttlSeconds] = await response.json();
  if (!token) throw new Error("GenerateIT returned no integrity token");
  return { token, ...(ttlSeconds ? { ttlSeconds } : {}) };
}

const webMinter = cachedMinter(() =>
  fetchWebChallenge().then((challenge) =>
    createMinter(challenge, generateWebIntegrityToken),
  ),
);

export async function mintWebPoToken(identifier) {
  try {
    const { minter, expiresAt } = await webMinter.get();
    return {
      token: await minter.mintAsWebsafeString(identifier),
      expiresAt,
    };
  } catch (error) {
    webMinter.reset();
    throw error;
  }
}
