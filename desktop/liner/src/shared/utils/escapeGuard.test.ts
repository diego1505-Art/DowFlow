import { describe, expect, it } from "vitest";
import { acquireEscapeGuard, isEscapeGuarded } from "./escapeGuard";

describe("escapeGuard", () => {
  it("is off by default and on while a guard is held", () => {
    expect(isEscapeGuarded()).toBe(false);
    const release = acquireEscapeGuard();
    expect(isEscapeGuarded()).toBe(true);
    release();
    expect(isEscapeGuarded()).toBe(false);
  });

  it("stays on until every holder has released", () => {
    const a = acquireEscapeGuard();
    const b = acquireEscapeGuard();
    a();
    expect(isEscapeGuarded()).toBe(true);
    b();
    expect(isEscapeGuarded()).toBe(false);
  });

  it("ignores a double release", () => {
    const a = acquireEscapeGuard();
    const b = acquireEscapeGuard();
    a();
    a();
    expect(isEscapeGuarded()).toBe(true);
    b();
    expect(isEscapeGuarded()).toBe(false);
  });
});
