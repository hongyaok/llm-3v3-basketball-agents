/**
 * Faithful port of Python `_number(value)` in `src/bball3x3/display/dashboard.py`.
 */
export function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean") {
    return null;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Recursively assert that a value contains no NaN or Infinity before JSON serialization
 * (mirrors Python's `json.dumps(..., allow_nan=False)`).
 */
export function assertNoNonFiniteNumbers(value: unknown, path = "$"): void {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`Non-finite number at ${path}: ${value}`);
    }
    return;
  }
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) {
      assertNoNonFiniteNumbers(value[i], `${path}[${i}]`);
    }
    return;
  }
  if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      assertNoNonFiniteNumbers(v, `${path}.${k}`);
    }
  }
}

