export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

type MatchMediaLike = (query: string) => { matches: boolean };

export function prefersReducedMotion(matchMediaLike?: MatchMediaLike | null): boolean {
  const matcher =
    matchMediaLike ??
    (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia.bind(window) : null);

  if (!matcher) {
    return false;
  }

  try {
    return matcher(REDUCED_MOTION_QUERY).matches;
  } catch {
    return false;
  }
}

export function motionDuration(baseMs: number, reducedMs = 0, reduceMotion = false): number {
  if (reduceMotion) {
    return Math.max(0, reducedMs);
  }
  return Math.max(0, baseMs);
}

