import { titleCase } from "../format";
import { useId } from "react";
import type { ParamSpecDTO } from "../types";

export type ParamValues = Record<string, unknown>;

export function defaultsFor(params: ParamSpecDTO[]): ParamValues {
  const out: ParamValues = {};
  for (const p of params) {
    out[p.name] =
      p.default !== undefined
        ? p.default
        : p.type === "bool"
          ? false
          : p.type === "choice"
            ? (p.choices?.[0] ?? "")
            : p.type === "str"
              ? ""
              : 0;
  }
  return out;
}

/** Form inputs generated from a parameter schema (docs/API.md `params`). */
export function ParamForm({
  params,
  values,
  onChange,
  compact = false,
}: {
  params: ParamSpecDTO[];
  values: ParamValues;
  onChange: (name: string, value: unknown) => void;
  compact?: boolean;
}) {
  // Several forms can share a page (one per player), so ids must be unique.
  const uid = useId();
  if (params.length === 0) return null;
  return (
    <div className={compact ? "param-form param-form-compact" : "param-form"}>
      {params.map((p) => {
        const value = values[p.name];
        const id = `${uid}-param-${p.name}`;
        let input;
        if (p.type === "bool") {
          input = (
            <input
              id={id}
              type="checkbox"
              checked={Boolean(value)}
              onChange={(e) => onChange(p.name, e.target.checked)}
            />
          );
        } else if (p.type === "choice" && p.choices) {
          input = (
            <select
              id={id}
              value={String(value ?? "")}
              onChange={(e) => onChange(p.name, e.target.value)}
            >
              {p.choices.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          );
        } else if (p.type === "int" || p.type === "float") {
          input = (
            <input
              id={id}
              type="number"
              value={value == null || value === "" ? "" : Number(value)}
              min={p.min ?? undefined}
              max={p.max ?? undefined}
              step={p.step ?? (p.type === "int" ? 1 : "any")}
              onChange={(e) => {
                const raw = e.target.value;
                if (raw === "") {
                  onChange(p.name, null);
                  return;
                }
                const n = p.type === "int" ? parseInt(raw, 10) : parseFloat(raw);
                onChange(p.name, Number.isNaN(n) ? null : n);
              }}
            />
          );
        } else {
          input = (
            <input
              id={id}
              type="text"
              value={value == null ? "" : String(value)}
              onChange={(e) => onChange(p.name, e.target.value)}
            />
          );
        }
        return (
          <label
            key={p.name}
            className={p.type === "bool" ? "field field-inline" : "field"}
            htmlFor={id}
            title={p.description}
          >
            {p.type === "bool" ? (
              <>
                {input}
                <span>{titleCase(p.name)}</span>
              </>
            ) : (
              <>
                <span>
                  {titleCase(p.name)}
                  {p.min != null && p.max != null && (
                    <span className="muted"> · {p.min}–{p.max}</span>
                  )}
                </span>
                {input}
              </>
            )}
            {!compact && p.description && (
              <span className="param-help">{p.description}</span>
            )}
          </label>
        );
      })}
    </div>
  );
}
