import { useState } from 'react';
import { api } from '../api/client';

const SCALES: { key: 'understandable' | 'useful' | 'trustworthy'; label: string }[] = [
  { key: 'understandable', label: 'Easy to understand' },
  { key: 'useful', label: 'Useful' },
  { key: 'trustworthy', label: 'Trustworthy' },
];

function savedRater(): string {
  try { return localStorage.getItem('tiles_rater') || ''; } catch { return ''; }
}

/** Collects a participant's 1-5 ratings of one move's explanation (human-centred evaluation). */
export default function FeedbackWidget({ sessionId, stepId }: { sessionId: string; stepId: number }) {
  const [rater, setRater] = useState(savedRater());
  const [scores, setScores] = useState<Record<string, number>>({});
  const [comment, setComment] = useState('');
  const [status, setStatus] = useState<'idle' | 'sending' | 'done' | 'error'>('idle');

  const complete = rater.trim() && SCALES.every((s) => scores[s.key]);

  async function submit() {
    setStatus('sending');
    try {
      try { localStorage.setItem('tiles_rater', rater.trim()); } catch { /* storage unavailable */ }
      await api.feedback.submit({
        session_id: sessionId, step_id: stepId, rater: rater.trim(),
        understandable: scores.understandable, useful: scores.useful, trustworthy: scores.trustworthy,
        comment: comment.trim() || undefined,
      });
      setStatus('done');
    } catch {
      setStatus('error');
    }
  }

  if (status === 'done') {
    return <div className="text-[11px] text-teal-400 pt-1">Thanks - rating saved.</div>;
  }

  return (
    <div className="border-t border-gray-700/50 mt-2 pt-2 space-y-1.5" data-testid="feedback">
      <div className="text-[10px] text-gray-500">Rate this explanation (1 = poor, 5 = excellent)</div>
      {SCALES.map((s) => (
        <div key={s.key} className="flex items-center gap-2 text-[11px] text-gray-400">
          <span className="w-32">{s.label}</span>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              onClick={() => setScores({ ...scores, [s.key]: n })}
              className={`w-6 h-6 rounded ${scores[s.key] === n ? 'bg-teal-600 text-white' : 'bg-gray-700 hover:bg-gray-600'}`}
            >{n}</button>
          ))}
        </div>
      ))}
      <div className="flex gap-2">
        <input value={rater} onChange={(e) => setRater(e.target.value)} placeholder="Your name / ID" maxLength={40}
               className="bg-gray-800 text-xs rounded px-2 py-1 border border-gray-700 w-36" />
        <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (optional)" maxLength={500}
               className="bg-gray-800 text-xs rounded px-2 py-1 border border-gray-700 flex-1" />
        <button onClick={submit} disabled={!complete || status === 'sending'}
                className="px-3 py-1 bg-teal-700 hover:bg-teal-600 rounded text-xs disabled:opacity-40">Submit</button>
      </div>
      {status === 'error' && <div className="text-[11px] text-red-400">Could not save the rating.</div>}
    </div>
  );
}
