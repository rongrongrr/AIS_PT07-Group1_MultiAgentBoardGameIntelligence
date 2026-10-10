import type { PlayerProfileDTO } from "../types";

export function TraitBars({ traits }: { traits: Record<string, number> }) {
  const entries = Object.entries(traits).filter(([k]) => k !== "tempo_ms");
  if (entries.length === 0) return null;
  return (
    <div className="traits">
      {entries.map(([name, value]) => (
        <div key={name} className="trait-row" title={`${name}: ${value.toFixed(2)}`}>
          <span className="trait-name">{name.replace(/_/g, " ")}</span>
          <div className="bar-track bar-track-sm">
            <div
              className="bar-fill"
              style={{
                width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`,
              }}
            />
          </div>
          <span className="trait-value small muted">{value.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

export function ProfileCard({
  profile,
  compact = false,
}: {
  profile: PlayerProfileDTO;
  compact?: boolean;
}) {
  return (
    <div className="profile-card">
      <div className="profile-card-header">
        <span className="player-name">{profile.player_name}</span>
        <span className="archetype-chip">{profile.archetype.replace(/_/g, " ")}</span>
      </div>
      <div className="confidence-row">
        <span className="small muted">
          confidence {Math.round(profile.confidence * 100)}% · {profile.moves_observed} moves
        </span>
        <div className="bar-track">
          <div
            className="bar-fill"
            style={{ width: `${Math.round(profile.confidence * 100)}%` }}
          />
        </div>
      </div>
      {!compact && <TraitBars traits={profile.traits ?? {}} />}
      {profile.summary && <p className="small muted">{profile.summary}</p>}
    </div>
  );
}
