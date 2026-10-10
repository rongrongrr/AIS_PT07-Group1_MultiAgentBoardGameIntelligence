import { useEffect, useState } from "react";
import { api } from "./api/client";
import { hrefFor, useHashRoute, VIEWS } from "./router";
import type { HealthDTO } from "./types";
import { Agents } from "./views/Agents";
import { Dashboard } from "./views/Dashboard";
import { Experiments } from "./views/Experiments";
import { Monitor } from "./views/Monitor";
import { Profiles } from "./views/Profiles";
import { Replay } from "./views/Replay";
import { Rulebook } from "./views/Rulebook";
import { Sessions } from "./views/Sessions";

export default function App() {
  const { route, navigate } = useHashRoute();
  const [health, setHealth] = useState<HealthDTO | null>(null);
  const [healthError, setHealthError] = useState(false);

  useEffect(() => {
    const load = () =>
      api
        .health()
        .then((h) => {
          setHealth(h);
          setHealthError(false);
        })
        .catch(() => setHealthError(true));
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
  }, []);

  const view = (() => {
    switch (route.view) {
      case "sessions":
        return <Sessions onStarted={(id) => navigate("monitor", id)} />;
      case "monitor":
        return <Monitor sessionId={route.id} />;
      case "replay":
        return <Replay sessionId={route.id} onPick={(id) => navigate("replay", id)} />;
      case "profiles":
        return <Profiles sessionId={route.id} onPick={(id) => navigate("profiles", id)} />;
      case "experiments":
        return <Experiments runId={route.id} onPick={(id) => navigate("experiments", id)} />;
      case "rulebook":
        return <Rulebook />;
      case "agents":
        return <Agents />;
      default:
        return <Dashboard />;
    }
  })();

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href={hrefFor("dashboard")}>
          <span className="brand-tiles">
            <span className="tile tile-blue tile-sm" />
            <span className="tile tile-yellow tile-sm" />
            <span className="tile tile-red tile-sm" />
          </span>
          TILES
          <span className="brand-sub">Explainable Multi-Agent Azul</span>
        </a>
        <nav>
          {VIEWS.map((v) => (
            <a
              key={v.name}
              className={`nav-item${route.view === v.name ? " nav-item-active" : ""}`}
              href={hrefFor(v.name)}
            >
              {v.label}
            </a>
          ))}
        </nav>
        <div className="health">
          <span
            className={`ws-dot ${healthError ? "ws-closed" : health ? "ws-open" : "ws-connecting"}`}
            title={
              healthError
                ? "Backend unreachable — start it with `tiles serve`"
                : health
                  ? `Backend OK · v${health.version}`
                  : "checking backend…"
            }
          />
          {health && health.live_available === false && (
            <span
              className="cap-badge"
              title="Live play on buddyboardgames.com is unavailable: pip install 'tiles[live]' && playwright install chromium"
            >
              No Live
            </span>
          )}
          {health && health.llm_available === false && (
            <span
              className="cap-badge"
              title="LLM explainer/extractor unavailable: set ANTHROPIC_API_KEY on the backend"
            >
              No LLM
            </span>
          )}
        </div>
      </header>
      <main>{view}</main>
    </div>
  );
}
