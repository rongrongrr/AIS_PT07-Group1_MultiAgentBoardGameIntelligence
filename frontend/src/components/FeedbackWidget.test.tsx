import { describe, it, expect, vi, beforeEach } from 'vitest';
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react';
import FeedbackWidget from './FeedbackWidget';
import { api } from '../api/client';

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

function rate(label: string, n: number) {
  const row = screen.getByText(label).parentElement!;
  fireEvent.click(Array.from(row.querySelectorAll('button')).find((b) => b.textContent === String(n))!);
}

describe('FeedbackWidget', () => {
  it('cannot be submitted until a name and all three ratings are given', () => {
    render(<FeedbackWidget sessionId="s1" stepId={3} />);
    const submit = screen.getByRole('button', { name: 'Submit' });
    expect(submit).toBeDisabled();
    rate('Easy to understand', 4);
    rate('Useful', 5);
    expect(submit).toBeDisabled();
    rate('Trustworthy', 3);
    expect(submit).toBeDisabled(); // still no name
    fireEvent.change(screen.getByLabelText('Participant ID'), { target: { value: 'p7' } });
    expect(submit).toBeEnabled();
  });

  it('sends the ratings, remembers the rater and thanks the user', async () => {
    const spy = vi.spyOn(api.feedback, 'submit').mockResolvedValue({ id: 1 });
    render(<FeedbackWidget sessionId="s1" stepId={3} />);
    fireEvent.change(screen.getByLabelText('Participant ID'), { target: { value: ' p7 ' } });
    fireEvent.change(screen.getByPlaceholderText('Comment (optional)'), { target: { value: 'clear' } });
    rate('Easy to understand', 4); rate('Useful', 5); rate('Trustworthy', 3);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(screen.getByText(/rating saved/)).toBeInTheDocument());
    expect(spy).toHaveBeenCalledWith({
      session_id: 's1', step_id: 3, rater: 'p7', understandable: 4, useful: 5, trustworthy: 3, comment: 'clear',
    });
    expect(localStorage.getItem('tiles_rater')).toBe('p7');
  });

  it('tells the parent when a rating was saved and offers to rate again', async () => {
    vi.spyOn(api.feedback, 'submit').mockResolvedValue({ id: 2 });
    const onSaved = vi.fn();
    render(<FeedbackWidget sessionId="s1" stepId={4} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText('Participant ID'), { target: { value: 'p1' } });
    rate('Easy to understand', 5); rate('Useful', 5); rate('Trustworthy', 5);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));

    cleanup();
    render(<FeedbackWidget sessionId="s1" stepId={9} alreadyRated />);          // a step rated earlier
    expect(screen.getByText(/rating saved/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Rate again' }));
    expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument();
  });

  it('prefills the rater and reports a failed save', async () => {
    localStorage.setItem('tiles_rater', 'returning');
    vi.spyOn(api.feedback, 'submit').mockRejectedValue(new Error('down'));
    render(<FeedbackWidget sessionId="s1" stepId={1} />);
    expect(screen.getByLabelText('Participant ID')).toHaveValue('returning');
    rate('Easy to understand', 1); rate('Useful', 1); rate('Trustworthy', 1);
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText(/Could not save/)).toBeInTheDocument();
  });
});
