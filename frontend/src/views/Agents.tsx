import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AgentInfoDTO, AgentsDTO } from "../types";

const NODES = [
  { id: "sense", label: "sense", sub: "snapshot + legal moves" },
  { id: "profile", label: "profile", sub: "Profiler" },
  { id: "decide", label: "decide", sub: "Tactician" },
  { id: "validate", label: "validate", sub: "Validator" },
  { id: "execute", label: "execute", sub: "engine / site" },
  { id: "observe", label: "observe", sub: "Profiler" },
  { id: "explain", label: "explain", sub: "Explainer" },
];

/** The per-turn Decision Stack pipeline as an inline SVG. */
function PipelineDiagram() {
  const w = 760;
  const h = 230;
  const boxW = 88;
  const boxH = 46;
  const gap = (w - 40 - NODES.length * boxW) / (NODES.length - 1);
  const x = (i: number) => 20 + i * (boxW + gap);
  const yMid = 110;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="pipeline-svg" role="img" aria-label="Decision Stack turn pipeline">
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#6b7280" />
        </marker>
        <marker id="arrow-reject" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 Z" fill="#dc2626" />
        </marker>
      </defs>
      {NODES.map((n, i) => (
        <g key={n.id}>
          {i < NODES.length - 1 && (
            <line
              x1={x(i) + boxW}
              y1={yMid}
              x2={x(i + 1) - 2}
              y2={yMid}
              stroke="#6b7280"
              strokeWidth={1.5}
              markerEnd="url(#arrow)"
            />
          )}
          <rect
            x={x(i)}
            y={yMid - boxH / 2}
            width={boxW}
            height={boxH}
            rx={8}
            fill={n.id === "validate" ? "#eef2ff" : "#ffffff"}
            stroke={n.id === "validate" ? "#4f46e5" : "#e2e5ea"}
            strokeWidth={1.5}
          />
          <text x={x(i) + boxW / 2} y={yMid - 3} textAnchor="middle" className="pipe-label">
            {n.label}
          </text>
          <text x={x(i) + boxW / 2} y={yMid + 13} textAnchor="middle" className="pipe-sub">
            {n.sub}
          </text>
        </g>
      ))}
      {/* Validator reject edge back to decide */}
      <path
        d={`M${x(3) + boxW / 2},${yMid + boxH / 2} V${yMid + 58} H${x(2) + boxW / 2} V${yMid + boxH / 2 + 2}`}
        fill="none"
        stroke="#dc2626"
        strokeWidth={1.5}
        markerEnd="url(#arrow-reject)"
      />
      <text x={(x(2) + x(3) + boxW) / 2} y={yMid + 72} textAnchor="middle" className="pipe-sub pipe-reject">
        reject + violated predicate (≤ 2 retries, then greedy fallback)
      </text>
      {/* Profiler prediction into the tactician */}
      <path
        d={`M${x(1) + boxW / 2},${yMid - boxH / 2} V${yMid - 50} H${x(2) + boxW / 2} V${yMid - boxH / 2 - 2}`}
        fill="none"
        stroke="#a21caf"
        strokeWidth={1.5}
        markerEnd="url(#arrow)"
      />
      <text x={(x(1) + x(2) + boxW) / 2} y={yMid - 56} textAnchor="middle" className="pipe-sub">
        predicted opponent policy → MCTS priors
      </text>
      {/* Explainer to the UI */}
      <path
        d={`M${x(6) + boxW / 2},${yMid - boxH / 2} V${yMid - 50}`}
        fill="none"
        stroke="#0e7490"
        strokeWidth={1.5}
        markerEnd="url(#arrow)"
      />
      <text x={x(6) + boxW} y={yMid - 56} textAnchor="end" className="pipe-sub">
        rationale → XAI panel + ledger
      </text>
      <text x={20} y={h - 10} className="pipe-sub">
        Every turn: the Validator is the only authority on legality; the Tactician never acts on its own initiative.
      </text>
    </svg>
  );
}

function AgentCard({ info, role }: { info: AgentInfoDTO; role: string }) {
  return (
    <div className="agent-card">
      <div className="agent-card-head">
        <span className="role-chip">{role}</span>
        <strong>{info.name}</strong>
        {info.class && <span className="mono small muted">{info.class}</span>}
        {info.uses_opponent_model && <span className="concept-chip">opponent-aware</span>}
        {info.requires && <span className="warn-chip">needs {info.requires}</span>}
      </div>
      {info.description && <p className="small">{info.description}</p>}
      {info.params && info.params.length > 0 && (
        <table className="data-table small">
          <thead>
            <tr>
              <th>param</th>
              <th>type</th>
              <th>default</th>
              <th>range</th>
              <th>description</th>
            </tr>
          </thead>
          <tbody>
            {info.params.map((p) => (
              <tr key={p.name}>
                <td className="mono">{p.name}</td>
                <td>{p.type}</td>
                <td className="num">{p.default === undefined ? "—" : String(p.default)}</td>
                <td className="num">{p.min != null || p.max != null ? `${p.min ?? ""}–${p.max ?? ""}` : "—"}</td>
                <td className="muted">{p.description ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function Agents() {
  const [agents, setAgents] = useState<AgentsDTO | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.agents().then(setAgents).catch((e) => setError(`Backend unreachable: ${e.message}`));
  }, []);

  return (
    <div className="page">
      <h2>The Decision Stack</h2>
      <p className="muted">
        Four specialized agents behind interfaces: a <strong>Validator</strong> (deterministic rules
        engine and per-turn coordinator), a <strong>Tactician</strong> (move proposal), a{" "}
        <strong>Profiler</strong> (opponent modeling and archetypes) and an <strong>Explainer</strong>{" "}
        (rationales). Implementations can be swapped per session without touching the play engine.
      </p>
      <div className="card">
        <PipelineDiagram />
      </div>
      {error && <div className="error-banner">{error}</div>}
      {agents && (
        <>
          <h3>Tacticians</h3>
          <div className="agent-grid">
            {agents.tacticians.map((t) => (
              <AgentCard key={t.name} info={t} role="tactician" />
            ))}
          </div>
          <h3>Profilers</h3>
          <div className="agent-grid">
            {agents.profilers.map((p) => (
              <AgentCard key={p.name} info={p} role="profiler" />
            ))}
          </div>
          <h3>Explainers</h3>
          <div className="agent-grid">
            {agents.explainers.map((x) => (
              <AgentCard key={x.name} info={x} role="explainer" />
            ))}
          </div>
          {agents.validator && (
            <>
              <h3>Validator</h3>
              <div className="agent-grid">
                <AgentCard info={agents.validator} role="validator" />
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
