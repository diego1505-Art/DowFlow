function decodeCloudFrontPolicy(policy: string): unknown {
  const base64 = policy
    .replace(/-/g, "+")
    .replace(/_/g, "=")
    .replace(/~/g, "/");
  return JSON.parse(atob(base64));
}

function policyEpoch(policy: unknown): number | undefined {
  if (
    typeof policy !== "object" ||
    policy === null ||
    !("Statement" in policy) ||
    !Array.isArray(policy.Statement)
  )
    return undefined;
  const statement: unknown = policy.Statement[0];
  if (
    typeof statement !== "object" ||
    statement === null ||
    !("Condition" in statement)
  )
    return undefined;
  const condition = statement.Condition;
  if (
    typeof condition !== "object" ||
    condition === null ||
    !("DateLessThan" in condition)
  )
    return undefined;
  const dateLessThan = condition.DateLessThan;
  if (
    typeof dateLessThan !== "object" ||
    dateLessThan === null ||
    !("AWS:EpochTime" in dateLessThan)
  )
    return undefined;
  const epoch = dateLessThan["AWS:EpochTime"];
  return typeof epoch === "number" && epoch > 0 ? epoch : undefined;
}

export function signedUrlExpiry(url: string): Date | null {
  try {
    const parsed = new URL(url);
    const expires = Number.parseInt(
      parsed.searchParams.get("Expires") ??
        parsed.searchParams.get("expires") ??
        "",
      10,
    );
    if (expires > 0) return new Date(expires * 1000);
    const policy = parsed.searchParams.get("Policy");
    const epoch = policy
      ? policyEpoch(decodeCloudFrontPolicy(policy))
      : undefined;
    return epoch ? new Date(epoch * 1000) : null;
  } catch {
    return null;
  }
}
