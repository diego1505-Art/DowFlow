import { describe, expect, it } from "vitest";
import { isRadioContext, nextRepeatMode, shouldRefillRadio } from "./radioMode";

describe("radio mode", () => {
  it("recognises radio contexts only", () => {
    expect(isRadioContext("radio:abc")).toBe(true);
    expect(isRadioContext("playlist:abc")).toBe(false);
    expect(isRadioContext(null)).toBe(false);
  });

  it("repeat cycles off -> all -> one -> off normally", () => {
    expect(nextRepeatMode("off", false)).toBe("all");
    expect(nextRepeatMode("all", false)).toBe("one");
    expect(nextRepeatMode("one", false)).toBe("off");
  });

  it("radio has no repeat-all: off <-> one", () => {
    expect(nextRepeatMode("off", true)).toBe("one");
    expect(nextRepeatMode("one", true)).toBe("off");
    expect(nextRepeatMode("all", true)).toBe("off");
  });

  it("refills when one track (or none) is left after the current one", () => {
    expect(shouldRefillRadio(20, 17)).toBe(false);
    expect(shouldRefillRadio(20, 18)).toBe(true);
    expect(shouldRefillRadio(20, 19)).toBe(true);
    expect(shouldRefillRadio(1, 0)).toBe(true);
    expect(shouldRefillRadio(5, -1)).toBe(false);
  });
});
