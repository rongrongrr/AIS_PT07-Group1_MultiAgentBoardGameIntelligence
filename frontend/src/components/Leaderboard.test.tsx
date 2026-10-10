import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import Leaderboard from './Leaderboard';
import { api } from '../api/client';

afterEach(() => vi.restoreAllMocks());

describe('Leaderboard', () => {
  it('shows the ranking and the win-rate matrix', async () => {
    vi.spyOn(api.tournament, 'latest').mockResolvedValue({
      available: true, generated: '2026-10-10', games: 10, deals_per_pair: 2,
      ranking: [{ player: 'A', elo: 1600, mean_score: 50 }, { player: 'B', elo: 1400, mean_score: 40 }],
      win_rates: { A: { B: 0.75 }, B: { A: 0.25 } },
    });
    render(<Leaderboard />);
    expect(await screen.findByTestId('leaderboard')).toBeInTheDocument();
    expect(screen.getByText('1600')).toBeInTheDocument();
    expect(screen.getByText('0.75')).toBeInTheDocument();
  });

  it('explains how to produce results when none exist', async () => {
    vi.spyOn(api.tournament, 'latest').mockResolvedValue({ available: false });
    render(<Leaderboard />);
    expect(await screen.findByText(/No tournament results saved yet/)).toBeInTheDocument();
  });

  it('reports errors', async () => {
    vi.spyOn(api.tournament, 'latest').mockRejectedValue(new Error('boom'));
    render(<Leaderboard />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });
});
