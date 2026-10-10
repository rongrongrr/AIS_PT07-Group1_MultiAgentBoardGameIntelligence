import { useState } from "react";
import { SessionConfig } from "./views/SessionConfig";
import { LiveMonitor } from "./views/LiveMonitor";
import { Replay } from "./views/Replay";

type View = "config" | "monitor" | "replay";

export default function App() {
  const [view, setView] = useState<View>("config");
  const [sessionId, setSessionId] = useState<string | null>(null);

  const navItem = (v: View, label: string) => (
    <button
      className={`nav-item${view === v ? " nav-item-active" : ""}`}
      onClick={() => setView(v)}
    >
      {label}
    </button>
  );

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">
          <span className="brand-tiles">
            <span className="tile tile-blue tile-sm" />
            <span className="tile tile-yellow tile-sm" />
            <span className="tile tile-red tile-sm" />
          </span>
          TILES
          <span className="brand-sub">explainable multi-agent Azul</span>
        </span>
        <nav>
          {navItem("config", "New session")}
          {navItem("monitor", "Monitor")}
          {navItem("replay", "Replay")}
        </nav>
      </header>
      <main>
        {view === "config" && (
          <SessionConfig
            onStarted={(id) => {
              setSessionId(id);
              setView("monitor");
            }}
          />
        )}
        {view === "monitor" && (
          <LiveMonitor sessionId={sessionId} onPick={setSessionId} />
        )}
        {view === "replay" && <Replay />}
      </main>
    </div>
  );
}
