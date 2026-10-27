import type { GameReplay } from "./types";

const replayCache = new Map<string, GameReplay>();
const MAX_CACHE_SIZE = 4;

export async function fetchGameReplay(
  experimentId: string,
  gameId: string,
  signal?: AbortSignal
): Promise<GameReplay> {
  const key = `${experimentId}:${gameId}`;
  const cached = replayCache.get(key);
  if (cached) {
    // Refresh LRU order
    replayCache.delete(key);
    replayCache.set(key, cached);
    return cached;
  }

  const url = `/data/replays/${encodeURIComponent(
    experimentId
  )}/${encodeURIComponent(gameId)}.json`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Failed to load replay for ${gameId} (${response.status})`);
  }
  const data = (await response.json()) as GameReplay;

  if (replayCache.size >= MAX_CACHE_SIZE) {
    const oldestKey = replayCache.keys().next().value;
    if (oldestKey) replayCache.delete(oldestKey);
  }
  replayCache.set(key, data);
  return data;
}

