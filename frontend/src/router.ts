import { useCallback, useEffect, useState } from "react";

export type ViewName =
  | "dashboard"
  | "sessions"
  | "monitor"
  | "replay"
  | "profiles"
  | "experiments"
  | "rulebook"
  | "agents";

export const VIEWS: { name: ViewName; label: string }[] = [
  { name: "dashboard", label: "Dashboard" },
  { name: "sessions", label: "Sessions" },
  { name: "monitor", label: "Monitor" },
  { name: "replay", label: "Replay" },
  { name: "profiles", label: "Profiles" },
  { name: "experiments", label: "Experiments" },
  { name: "rulebook", label: "Rulebook" },
  { name: "agents", label: "Agents" },
];

export interface Route {
  view: ViewName;
  /** First path segment after the view, e.g. the session id. */
  id: string | null;
}

function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const view = VIEWS.find((v) => v.name === parts[0])?.name ?? "dashboard";
  return { view, id: parts[1] ? decodeURIComponent(parts[1]) : null };
}

export function hrefFor(view: ViewName, id?: string | null): string {
  return id ? `#/${view}/${encodeURIComponent(id)}` : `#/${view}`;
}

/** Minimal hash router: `#/monitor/<id>` → { view: "monitor", id }. */
export function useHashRoute(): {
  route: Route;
  navigate: (view: ViewName, id?: string | null) => void;
} {
  const [route, setRoute] = useState<Route>(() =>
    parseHash(window.location.hash),
  );

  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  const navigate = useCallback((view: ViewName, id?: string | null) => {
    window.location.hash = hrefFor(view, id);
  }, []);

  return { route, navigate };
}
