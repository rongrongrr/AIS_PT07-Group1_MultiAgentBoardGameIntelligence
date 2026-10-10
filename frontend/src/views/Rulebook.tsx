import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RulebookDTO, RulebookSearchDTO, RulesDTO } from "../types";

export function Rulebook() {
  const [book, setBook] = useState<RulebookDTO | null>(null);
  const [sectionId, setSectionId] = useState<string>("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<RulebookSearchDTO | null>(null);
  const [rules, setRules] = useState<RulesDTO | null>(null);
  const [extractor, setExtractor] = useState("deterministic");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .rulebook()
      .then((b) => {
        setBook(b);
        if (b.sections.length > 0) setSectionId(b.sections[0].id);
      })
      .catch((e) => setError(`Backend unreachable: ${e.message}`));
  }, []);

  useEffect(() => {
    setBusy(true);
    api
      .rules(extractor)
      .then(setRules)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }, [extractor]);

  const runSearch = () => {
    if (!query.trim()) return;
    api.rulebookSearch(query.trim(), 6).then(setSearch).catch((e) => setError(e.message));
  };

  const section = book?.sections.find((s) => s.id === sectionId) ?? null;
  const maxScore = search ? Math.max(...search.results.map((r) => r.score), 0) || 1 : 1;

  return (
    <div className="page">
      <h2>Rulebook</h2>
      <p className="muted">
        The RAG-to-Logic pipeline: the English rulebook is chunked and indexed, rules are extracted
        into machine-readable specs, and every spec is verified against the deterministic rules
        engine. The engine stays the source of truth; no language model sits in the move path.
      </p>
      {error && <div className="error-banner">{error}</div>}

      <div className="card">
        <h3>Ask the rulebook</h3>
        <div className="row-gap">
          <input
            className="grow"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            placeholder="e.g. what happens when the floor line overflows?"
          />
          <button className="btn-primary" onClick={runSearch} type="button">
            Search
          </button>
        </div>
        {search && (
          <div className="search-results">
            {search.results.length === 0 && <p className="muted small">No matching passages.</p>}
            {search.results.map((r, i) => (
              <div key={i} className="search-result">
                <div className="search-result-head">
                  <button className="link-button" onClick={() => setSectionId(r.section)} type="button">
                    §{r.section}
                  </button>
                  <div className="bar-track bar-track-sm">
                    <div className="bar-fill" style={{ width: `${Math.round((r.score / maxScore) * 100)}%` }} />
                  </div>
                  <span className="small muted">{r.score.toFixed(2)}</span>
                </div>
                <p className="small">{r.text}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="two-col two-col-wide">
        <div className="card rulebook-browser">
          <div className="section-list">
            {book?.sections.map((s) => (
              <button
                key={s.id}
                className={`section-item${s.id === sectionId ? " section-item-active" : ""}`}
                onClick={() => setSectionId(s.id)}
                type="button"
              >
                {s.title}
              </button>
            ))}
          </div>
          <div className="section-text">
            {section ? (
              <>
                <h3>{section.title}</h3>
                <p className="rule-text">{section.text}</p>
              </>
            ) : (
              <p className="muted">Loading rulebook…</p>
            )}
          </div>
        </div>

        <div className="card">
          <div className="monitor-header">
            <h3 className="no-margin">Extracted rules</h3>
            <span className="spacer" />
            <label className="field-inline small">
              extractor
              <select value={extractor} onChange={(e) => setExtractor(e.target.value)}>
                <option value="deterministic">deterministic (retrieval + parsing)</option>
                <option value="llm">llm (Claude; needs API key)</option>
              </select>
            </label>
          </div>
          {busy && <p className="muted small">Extracting and verifying…</p>}
          {rules && (
            <>
              <div className="stat-grid stat-grid-tight">
                <div className="stat-tile">
                  <div className="stat-label">Verification accuracy</div>
                  <div className="stat-value">{Math.round(rules.accuracy * 100)}%</div>
                  <div className="stat-hint muted small">
                    {rules.verified}/{rules.checked} verified · {rules.skipped} skipped · ran {rules.extractor}
                  </div>
                </div>
              </div>
              <div className="table-scroll">
                <table className="data-table rules-table">
                  <thead>
                    <tr>
                      <th>rule</th>
                      <th>kind</th>
                      <th>predicate</th>
                      <th>parameters</th>
                      <th>status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rules.rules.map((r) => (
                      <tr key={r.id} title={r.text}>
                        <td>
                          <div>{r.id}</div>
                          <div className="small muted">§{r.section}</div>
                        </td>
                        <td>{r.kind}</td>
                        <td className="mono small">{r.predicate ?? "—"}</td>
                        <td className="mono small params-cell">
                          {Object.keys(r.parameters ?? {}).length ? JSON.stringify(r.parameters) : "—"}
                        </td>
                        <td>
                          <span className={`status-badge status-${r.status}`}>{r.status}</span>
                          {r.detail && <div className="small error-text">{r.detail}</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
