import { act, renderHook } from "@testing-library/react";
import { hrefFor, useHashRoute } from "./router";

describe("hrefFor", () => {
  it("builds hash links with optional encoded ids", () => {
    expect(hrefFor("dashboard")).toBe("#/dashboard");
    expect(hrefFor("monitor", "a b")).toBe("#/monitor/a%20b");
  });
});

describe("useHashRoute", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("defaults to the dashboard", () => {
    const { result } = renderHook(() => useHashRoute());
    expect(result.current.route).toEqual({ view: "dashboard", id: null });
  });

  it("parses the hash and ids", () => {
    window.location.hash = "#/replay/x%20y";
    const { result } = renderHook(() => useHashRoute());
    expect(result.current.route).toEqual({ view: "replay", id: "x y" });
  });

  it("falls back for unknown views", () => {
    window.location.hash = "#/nope";
    const { result } = renderHook(() => useHashRoute());
    expect(result.current.route.view).toBe("dashboard");
  });

  it("navigates and reacts to hashchange", () => {
    const { result } = renderHook(() => useHashRoute());
    act(() => {
      result.current.navigate("monitor", "s1");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current.route).toEqual({ view: "monitor", id: "s1" });
  });
});
