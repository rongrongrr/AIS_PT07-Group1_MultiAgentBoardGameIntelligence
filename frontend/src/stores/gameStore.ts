import { create } from 'zustand';
import type { GameStateData, MoveResponse, Session, SysLogEntry } from '../api/client';

interface GameStore {
  sessions: Session[];
  currentSession: Session | null;
  setSessions: (sessions: Session[]) => void;
  setCurrentSession: (session: Session | null) => void;
  updateSessionStatus: (id: string, status: string) => void;

  gameState: GameStateData | null;
  setGameState: (state: GameStateData | null) => void;

  moves: MoveResponse[];
  addMove: (move: MoveResponse) => void;
  setMoves: (moves: MoveResponse[]) => void;
  clearMoves: () => void;

  sysLogs: SysLogEntry[];
  addSysLog: (entry: SysLogEntry) => void;
  clearSysLogs: () => void;

  isConnected: boolean;
  setConnected: (connected: boolean) => void;
  error: string | null;
  setError: (error: string | null) => void;
}

export const useGameStore = create<GameStore>((set) => ({
  sessions: [],
  currentSession: null,
  setSessions: (sessions) => set({ sessions }),
  setCurrentSession: (session) => set({ currentSession: session }),
  updateSessionStatus: (id, status) =>
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === id ? { ...s, status } : s
      ),
      currentSession:
        state.currentSession?.id === id
          ? { ...state.currentSession, status }
          : state.currentSession,
    })),

  gameState: null,
  setGameState: (gameState) => set({ gameState }),

  moves: [],
  addMove: (move) => set((state) => ({ moves: [...state.moves, move] })),
  setMoves: (moves) => set({ moves }),
  clearMoves: () => set({ moves: [] }),

  sysLogs: [],
  addSysLog: (entry) =>
    set((state) => ({ sysLogs: [...state.sysLogs.slice(-200), entry] })),
  clearSysLogs: () => set({ sysLogs: [] }),

  isConnected: false,
  setConnected: (isConnected) => set({ isConnected }),
  error: null,
  setError: (error) => set({ error }),
}));
