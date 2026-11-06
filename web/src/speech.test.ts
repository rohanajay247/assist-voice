import { describe, expect, it } from "vitest";
import cases from "./speech-cases.json";
import { speakable } from "./speech";

describe("speakable", () => {
  it.each(cases as [string, string][])("%s", (input, spoken) => {
    expect(speakable(input)).toBe(spoken);
  });
});
