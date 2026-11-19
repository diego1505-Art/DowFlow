import { describe, expect, it } from "vitest";
import {
  DEFAULT_PRIMARY_API,
  isSecureBaseUrl,
  resolveApiBaseUrl,
} from "./baseUrl";

describe("api base url", () => {
  it("uses the primary api when no override is set", () => {
    expect(resolveApiBaseUrl(undefined)).toBe(DEFAULT_PRIMARY_API);
    expect(resolveApiBaseUrl("  ")).toBe(DEFAULT_PRIMARY_API);
  });

  it("accepts an https override and trims trailing slashes", () => {
    expect(resolveApiBaseUrl("https://staging.example.com/")).toBe(
      "https://staging.example.com",
    );
  });

  it("accepts plain http only to loopback", () => {
    for (const url of [
      "http://localhost:1337",
      "http://127.0.0.1:1337",
      "http://[::1]:1337",
    ]) {
      expect(isSecureBaseUrl(url)).toBe(true);
      expect(resolveApiBaseUrl(url)).toBe(url);
    }
  });

  it("refuses plain http to a remote host and malformed urls", () => {
    expect(resolveApiBaseUrl("http://edge.tryliner.fun:10518")).toBe(
      DEFAULT_PRIMARY_API,
    );
    expect(resolveApiBaseUrl("not a url")).toBe(DEFAULT_PRIMARY_API);
  });
});
