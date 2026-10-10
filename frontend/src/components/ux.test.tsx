import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AlternativesChart from './AlternativesChart';
import BoardSnapshot, { PatternsContext } from './BoardSnapshot';
import Help from './Help';
import { describeStatus } from './StatusBanner';
import SessionConfig, { validateConfig } from './SessionConfig';
import { wilson } from './Leaderboard';
import App from '../App';
import { api, type GameAction, type Session } from '../api/client';

afterEach(() => vi.restoreAllMocks());
beforeEach(() => localStorage.clear());

const act = (color: string, row: number | null, from = 0): GameAction => ({
  source_type: 'factory', source_index: from, color,
  destination: row === null ? 'floor' : 'pattern_line', destination_row: row,
});

describe('AlternativesChart', () => {
  it('marks the chosen move and scales bars to the best score', () => {
    render(<AlternativesChart chosen={act('red', 2)} alternatives={[
      { action: act('red', 2), score: 8 }, { action: act('blue', 1, 3), score: 4 }, { action: act('blue', null, 3), score: -2 },
    ]} />);
    expect(screen.getByText('(chosen)')).toBeInTheDocument();
    expect(screen.getByText(/red F1 → Row 3/)).toBeInTheDocument();
    expect(screen.getByText(/blue F4 → Floor/)).toBeInTheDocument();
    const bars = screen.getByTestId('alternatives').querySelectorAll<HTMLElement>('.h-1\\.5 > div');
    expect(parseFloat(bars[0].style.width)).toBe(100);
    expect(parseFloat(bars[2].style.width)).toBeLessThan(parseFloat(bars[1].style.width));
  });

  it('renders nothing without alternatives', () => {
    const { container } = render(<AlternativesChart chosen={act('red', 1)} alternatives={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('Help', () => {
  it('exposes its text to hover and to screen readers', () => {
    render(<Help text="Elo explained" />);
    const el = screen.getByRole('note');
    expect(el).toHaveAttribute('title', 'Elo explained');
    expect(el).toHaveAttribute('aria-label', 'Elo explained');
  });
});

describe('BoardSnapshot', () => {
  const board = {
    factories: [['red', 'blue', 'blue', 'black']], center_pool: ['firstPlayer', 'white'],
    players: [{ name: 'A', score: 3, pattern_lines: [['red'], [], [], [], []], wall: [[true, false, false, false, false], ...Array(4).fill(Array(5).fill(false))], floor_line: ['white'] }],
  };

  it('shows colour letters only when the colour-blind option is on', () => {
    const { rerender, container } = render(<BoardSnapshot board={board} action={act('red', 0)} activePlayer="A" />);
    expect(container.textContent).not.toMatch(/[BYRGW]{2,}/);
    expect(screen.queryByText('R')).toBeNull();
    rerender(<PatternsContext.Provider value><BoardSnapshot board={board} action={act('red', 0)} activePlayer="A" /></PatternsContext.Provider>);
    expect(screen.getAllByText('R').length).toBeGreaterThan(0);
    expect(screen.getAllByText('G').length).toBeGreaterThan(0);        // black tiles are drawn green
  });

  it('hides the move highlight and arrow in the after view', () => {
    render(<BoardSnapshot board={board} action={act('red', 0)} activePlayer="A" heading="Board state after this move" showMove={false} />);
    expect(screen.getByText('Board state after this move')).toBeInTheDocument();
    expect(screen.queryByText(/by A/)).toBeNull();
  });
});

describe('describeStatus', () => {
  const base: Session = {
    id: 's', room_name: 'room-1', platform_url: '', browser_mode: 'headless', status: 'created',
    player_config: [{ slot: 0, type: 'TilesMCTS', name: 'Alice' }, { slot: 1, type: 'human', name: 'Bob' }],
    profiler_config: null, move_timeout_sec: 10, stuck_abort_sec: 3, final_scores: null, winner: null,
    created_at: '', completed_at: null,
  };
  const state = (turn: string) => ({ current_turn: turn, round: 2, players: [], factories: [], center_pool: [] }) as never;

  it('explains each phase in plain language', () => {
    expect(describeStatus(null, null, 0, true).text).toMatch(/Loading/);
    expect(describeStatus(base, null, 0, true).text).toMatch(/Press Start/);
    const lobby = describeStatus({ ...base, status: 'lobby' }, null, 0, true);
    expect(lobby.tone).toBe('warn');
    expect(lobby.text).toMatch(/Bob.*room-1/);
    expect(describeStatus({ ...base, status: 'lobby', player_config: base.player_config.slice(0, 1) }, null, 0, true).text).toMatch(/joining/);
    const playing = { ...base, status: 'playing' };
    expect(describeStatus(playing, state('Alice'), 7, true).text).toMatch(/Alice \(TilesMCTS\) is choosing.*Round 2.*7 moves/);
    expect(describeStatus(playing, state('Bob'), 7, true).text).toMatch(/Waiting for Bob \(human\)/);
    expect(describeStatus(playing, null, 0, true).text).toMatch(/first board/);
    expect(describeStatus(playing, state('Alice'), 7, false).tone).toBe('warn');
  });

  it('reports the reason an aborted session stopped', () => {
    expect(describeStatus({ ...base, status: 'aborted', abort_reason: 'No progress for 20s' }, null, 3, true).text)
      .toBe('Aborted: No progress for 20s.');
    expect(describeStatus({ ...base, status: 'aborted' }, null, 3, true).text).toMatch(/no reason was recorded/);
    expect(describeStatus({ ...base, status: 'completed', winner: 'Alice' }, null, 51, true).text).toMatch(/winner: Alice/);
  });
});

describe('validateConfig', () => {
  const ok = [{ slot: 0, type: 'GreedyPlayer', name: 'A' }, { slot: 1, type: 'RandomPlayer', name: 'B' }];
  it('accepts a good configuration', () => expect(validateConfig('room-1', ok, ['GreedyPlayer', 'RandomPlayer'])).toEqual([]));
  it('lists every problem the server would reject', () => {
    expect(validateConfig('', ok, [])[0]).toMatch(/Enter a room name/);
    expect(validateConfig('a/b', ok, [])[0]).toMatch(/room name may only/);
    expect(validateConfig('r', [ok[0]], [])[0]).toMatch(/at least 2 players/);
    expect(validateConfig('r', [{ slot: 0, type: 'human', name: 'H1' }, { slot: 1, type: 'human', name: 'H2' }], []).join()).toMatch(/at least one bot/);
    expect(validateConfig('r', [ok[0], { ...ok[1], name: 'a' }], []).join()).toMatch(/different from each other/);
    expect(validateConfig('r', [{ ...ok[0], name: '<b>' }, ok[1]], []).join()).toMatch(/Player 1: the name/);
    expect(validateConfig('r', [{ ...ok[0], type: 'Nope' }, ok[1]], ['GreedyPlayer']).join()).toMatch(/unknown bot "Nope"/);
  });
});

describe('SessionConfig', () => {
  it('applies presets, explains the chosen bots and blocks an invalid form', async () => {
    vi.spyOn(api.players, 'list').mockResolvedValue({
      players: ['TilesMCTS', 'GreedyPlayer', 'MinimaxPlayer', 'RusherPlayer', 'BlockerPlayer'].map((name) => ({ name, type: 'player' })), profilers: [],
    });
    render(<SessionConfig />);
    expect(screen.getByTestId('first-run')).toBeInTheDocument();
    const create = screen.getByRole('button', { name: /Create Session/ });
    expect(create).toBeDisabled();                                      // no room name yet
    fireEvent.click(screen.getByRole('button', { name: '4-player mix' }));
    expect(screen.getByText(/Players \(4\/4\)/)).toBeInTheDocument();
    expect(screen.getByText(/Greedy style: finishes lines fast/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Room name'), { target: { value: 'a/b' } });
    expect(await screen.findByTestId('config-problems')).toHaveTextContent(/room name may only/);
    fireEvent.change(screen.getByLabelText('Room name'), { target: { value: 'good-room' } });
    await waitFor(() => expect(screen.getByRole('button', { name: /Create Session/ })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Me vs bot' }));
    expect(screen.getByText(/their moves are inferred from the board/)).toBeInTheDocument();
  });
});

describe('Leaderboard interval', () => {
  it('computes a Wilson interval that narrows with more games', () => {
    const [lo12, hi12] = wilson(0.67, 12);
    const [lo40, hi40] = wilson(0.67, 40);
    expect(hi12 - lo12).toBeGreaterThan(hi40 - lo40);
    expect(lo40).toBeLessThan(0.67);
    expect(hi40).toBeGreaterThan(0.67);
    expect(wilson(0.5, 0)).toEqual([0, 1]);
  });
});

describe('App shell', () => {
  const session = (id: string, room: string, status: string, winner: string | null = null): Session => ({
    id, room_name: room, platform_url: '', browser_mode: 'headless', status,
    player_config: [{ slot: 0, type: 'TilesMCTS', name: 'Alice' }, { slot: 1, type: 'GreedyPlayer', name: 'Bob' }],
    profiler_config: null, move_timeout_sec: 10, stuck_abort_sec: 3, final_scores: null, winner,
    created_at: '2026-01-01T00:00:00Z', completed_at: null,
  });

  it('filters the session list by search text and status, and toggles tile letters', async () => {
    vi.spyOn(api.sessions, 'list').mockResolvedValue([
      session('1', 'swift-fox-1', 'completed', 'Alice'), session('2', 'calm-owl-2', 'aborted'), session('3', 'bold-elk-3', 'playing'),
    ]);
    vi.spyOn(api.players, 'list').mockResolvedValue({ players: [], profilers: [] });
    render(<App />);
    expect(await screen.findByText('swift-fox-1')).toBeInTheDocument();
    expect(screen.getByText('Sessions (3)')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Filter sessions by status'), { target: { value: 'aborted' } });
    expect(screen.queryByText('swift-fox-1')).toBeNull();
    expect(screen.getByText('calm-owl-2')).toBeInTheDocument();
    expect(screen.getByText('Sessions (1 of 3)')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Filter sessions by status'), { target: { value: 'running' } });
    expect(screen.getByText('bold-elk-3')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Filter sessions by status'), { target: { value: 'all' } });
    fireEvent.change(screen.getByLabelText('Search sessions'), { target: { value: 'zzz' } });
    expect(screen.getByText(/No sessions match/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Tile letters/));
    expect(localStorage.getItem('tiles_patterns')).toBe('1');
    expect(screen.getAllByRole('tab').length).toBeGreaterThanOrEqual(2);

    fireEvent.change(screen.getByLabelText('Colour theme'), { target: { value: 'light' } });
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    expect(localStorage.getItem('tiles_theme')).toBe('light');
  });
});
