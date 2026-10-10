import { api, connectExperimentWs, connectSessionWs, downloadJson } from "./client";

function mockFetch(
  body: unknown,
  init: { ok?: boolean; status?: number; statusText?: string } = {},
) {
  const fn = vi.fn().mockResolvedValue({
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    json: () =>
      body instanceof Error ? Promise.reject(body) : Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("api requests", () => {
  it("returns parsed JSON", async () => {
    const fetchMock = mockFetch({ status: "ok", version: "1" });
    await expect(api.health()).resolves.toEqual({ status: "ok", version: "1" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  });

  it("sends JSON bodies", async () => {
    const fetchMock = mockFetch({});
    await api.createSession({ mode: "local", players: [], profiler: null, explainer: null });
    await api.startExperiment("tournament", { n: 1 });
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      kind: "tournament",
      params: { n: 1 },
    });
  });

  it("builds URLs for every endpoint", async () => {
    const fetchMock = mockFetch({});
    await api.agents();
    await api.listSessions();
    await api.getSession("a");
    await api.startSession("a");
    await api.stopSession("a");
    await api.deleteSession("a");
    await api.getHistory("a");
    await api.getProfiles("a");
    await api.archetypes();
    await api.analyzeSession("a", "b c");
    await api.experimentTypes();
    await api.listExperiments();
    await api.getExperiment("e");
    await api.stopExperiment("e");
    await api.deleteExperiment("e");
    await api.rulebook();
    await api.rulebookSearch("floor line");
    await api.rules();
    await api.rules("llm");
    await api.stats();
    const urls = fetchMock.mock.calls.map((c) => c[0]);
    expect(urls).toContain("/api/profiles/a/analyze?profiler=b%20c");
    expect(urls).toContain("/api/rulebook/search?q=floor%20line&k=5");
    expect(urls).toContain("/api/rulebook/rules");
    expect(urls).toContain("/api/rulebook/rules?extractor=llm");
    expect(api.exportUrl("a")).toBe("/api/history/a/export");
  });

  it("throws with the server's detail string", async () => {
    mockFetch({ detail: "nope" }, { ok: false, status: 404 });
    await expect(api.health()).rejects.toThrow("404 nope");
  });

  it("serialises structured details", async () => {
    mockFetch({ detail: [{ msg: "bad" }] }, { ok: false, status: 422 });
    await expect(api.health()).rejects.toThrow('422 [{"msg":"bad"}]');
  });

  it("falls back to the body or status text", async () => {
    mockFetch({ other: 1 }, { ok: false, status: 400 });
    await expect(api.health()).rejects.toThrow('400 {"other":1}');
    mockFetch(new Error("not json"), { ok: false, status: 500, statusText: "Boom" });
    await expect(api.health()).rejects.toThrow("500 Boom");
  });

  it("handles 204 responses", async () => {
    mockFetch(undefined, { status: 204 });
    await expect(api.deleteSession("a")).resolves.toBeUndefined();
  });
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn(() => this.onclose?.());
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
}

describe("websocket helpers", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.useFakeTimers();
  });

  it("connects, delivers events and ignores malformed frames", () => {
    const onEvent = vi.fn();
    const onStatus = vi.fn();
    const handle = connectSessionWs("s1", onEvent, onStatus);
    const ws = FakeSocket.instances[0];
    expect(ws.url).toMatch(/^ws:\/\/.*\/api\/sessions\/s1\/ws$/);
    ws.onopen?.();
    ws.onmessage?.({ data: '{"type":"log","level":"info","message":"x"}' });
    ws.onmessage?.({ data: "not json" });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onStatus.mock.calls.map((c) => c[0])).toEqual(["connecting", "open"]);
    handle.close();
    expect(onStatus).toHaveBeenLastCalledWith("closed");
  });

  it("reconnects with backoff after an error", () => {
    connectExperimentWs("e1", vi.fn());
    FakeSocket.instances[0].onerror?.();
    vi.advanceTimersByTime(1100);
    expect(FakeSocket.instances).toHaveLength(2);
    expect(FakeSocket.instances[1].url).toContain("/experiments/e1/ws");
  });

  it("stops reconnecting once closed by the caller", () => {
    const handle = connectSessionWs("s1", vi.fn());
    handle.close();
    vi.advanceTimersByTime(20000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("gives up after eight attempts", () => {
    connectSessionWs("s1", vi.fn());
    for (let i = 0; i < 12; i++) {
      FakeSocket.instances[FakeSocket.instances.length - 1].onclose?.();
      vi.advanceTimersByTime(9000);
    }
    expect(FakeSocket.instances).toHaveLength(9);
  });
});

describe("downloadJson", () => {
  it("clicks a temporary link", () => {
    const create = vi.fn(() => "blob:x");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    downloadJson("a.json", { a: 1 });
    expect(click).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledWith("blob:x");
  });
});
