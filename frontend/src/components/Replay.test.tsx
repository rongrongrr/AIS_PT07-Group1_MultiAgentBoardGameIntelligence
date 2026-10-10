import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import Replay from './Replay';
import { api, type MoveResponse } from '../api/client';

function board(tiles: number) {
  return {
    factories: [Array(tiles).fill('red')],
    center_pool: [] as string[],
    players: [
      { name: 'Alice', score: 0, pattern_lines: [[], [], [], [], []] as string[][], wall: Array(5).fill(Array(5).fill(false)) as boolean[][], floor_line: [] as string[] },
      { name: 'Bob', score: 0, pattern_lines: [[], [], [], [], []] as string[][], wall: Array(5).fill(Array(5).fill(false)) as boolean[][], floor_line: [] as string[] },
    ],
  };
}

function move(step: number, tiles: number, who = step % 2 ? 'Alice' : 'Bob', extra: Partial<MoveResponse> = {}): MoveResponse {
  return {
    step_id: step, player_name: who, system_tag: 'MinimaxPlayer',
    action: { source_type: 'factory', source_index: 0, color: 'red', destination: 'pattern_line', destination_row: 1 },
    decision_time_ms: 5, timestamp: '2026-01-01T00:00:00Z', board: board(tiles), ...extra,
  };
}

// tiles on the board jump up at step 4: that is a new round
const MOVES = [move(1, 20), move(2, 12), move(3, 4), move(4, 20, 'Bob', {
  commentary: 'Bob takes 4 red.',
  explanation: { model: 'MinimaxPlayer', chosen_score: 3, n_legal: 10, top_alternatives: [], rationale: 'Bob takes 4 red from Factory 1.' },
}), move(5, 10)];

beforeEach(() => {
  vi.spyOn(api.history, 'get').mockResolvedValue({ session_id: 's', room_name: 'r', total_moves: MOVES.length, moves: MOVES });
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('Replay', () => {
  it('shows the first move and steps with Next / Prev', async () => {
    render(<Replay sessionId="s" />);
    expect(await screen.findByText('Move 1 / 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Prev/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(screen.getByText('Move 2 / 5')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Prev/ }));
    expect(screen.getByText('Move 1 / 5')).toBeInTheDocument();
  });

  it('jumps with the slider, the end button and the round selector', async () => {
    render(<Replay sessionId="s" />);
    await screen.findByText('Move 1 / 5');
    fireEvent.change(screen.getByLabelText('Jump to move'), { target: { value: '2' } });
    expect(screen.getByText('Move 3 / 5')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Jump to end'));
    expect(screen.getByText('Move 5 / 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Next/ })).toBeDisabled();
    fireEvent.click(screen.getByTitle('Jump to start'));
    expect(screen.getByText('Move 1 / 5')).toBeInTheDocument();
    // a refill of the factories at move 4 starts round 2
    fireEvent.change(screen.getByDisplayValue('Round 1'), { target: { value: '1' } });
    expect(screen.getByText('Move 4 / 5')).toBeInTheDocument();
  });

  it('plays automatically, pauses, and stops at the last move', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<Replay sessionId="s" />);
    await screen.findByText('Move 1 / 5');
    fireEvent.click(screen.getByRole('button', { name: /Play/ }));
    expect(screen.getByRole('button', { name: /Pause/ })).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(1300); });
    expect(screen.getByText('Move 2 / 5')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Pause/ }));
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(screen.getByText('Move 2 / 5')).toBeInTheDocument(); // paused: no movement
    fireEvent.click(screen.getByRole('button', { name: /Play/ }));
    await act(async () => { vi.advanceTimersByTime(10000); });
    expect(screen.getByText('Move 5 / 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Play/ })).toBeInTheDocument(); // stopped at the end
  });

  it('shows the commentary and rationale of the current move', async () => {
    render(<Replay sessionId="s" />);
    await screen.findByText('Move 1 / 5');
    expect(screen.queryByText(/Bob takes 4 red from Factory 1/)).toBeNull();
    fireEvent.change(screen.getByLabelText('Jump to move'), { target: { value: '3' } });
    expect(screen.getByText(/Bob takes 4 red from Factory 1/)).toBeInTheDocument();
    expect(screen.getByText(/Bob takes 4 red\./)).toBeInTheDocument();
    expect(screen.getByTestId('feedback')).toBeInTheDocument();
  });

  it('shows only the scores in the control condition (?explain=scores)', async () => {
    window.history.pushState({}, '', '/?explain=scores');
    try {
      render(<Replay sessionId="s" />);
      await screen.findByText('Move 1 / 5');
      fireEvent.change(screen.getByLabelText('Jump to move'), { target: { value: '3' } });
      expect(screen.getByTestId('scores-only')).toBeInTheDocument();
      expect(screen.queryByText(/Bob takes 4 red from Factory 1/)).toBeNull();
      expect(screen.queryByText(/Bob takes 4 red\./)).toBeNull();
      expect(screen.getByTestId('feedback')).toBeInTheDocument();
    } finally {
      window.history.pushState({}, '', '/');
    }
  });

  it('explains when nothing was recorded or loading fails', async () => {
    vi.spyOn(api.history, 'get').mockResolvedValueOnce({ session_id: 's', room_name: 'r', total_moves: 0, moves: [] });
    const { unmount } = render(<Replay sessionId="empty" />);
    expect(await screen.findByText(/No recorded moves/)).toBeInTheDocument();
    unmount();
    vi.spyOn(api.history, 'get').mockRejectedValueOnce(new Error('boom'));
    render(<Replay sessionId="bad" />);
    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument());
  });
});
