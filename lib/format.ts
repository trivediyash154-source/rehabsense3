/**
 * Rendering values that may genuinely be absent.
 *
 * A metric the backend could not compute is `null`, not `0`. Printing "0"
 * or "0%" states a measured result of zero, which is a different and much
 * stronger claim than "we could not measure this".
 */

/** An em dash, the house convention for "no value". */
export const NO_VALUE = "—";

export function metric(
  value: number | null | undefined,
  unit = "",
  fallback: string = NO_VALUE,
): string {
  if (value == null || !Number.isFinite(value)) return fallback;
  return `${Math.round(value)}${unit}`;
}

/** The recovery indicator, or an explicit statement that it was not scored. */
export function score(value: number | null | undefined, suffix = "/100"): string {
  return value == null ? "Unscored" : `${Math.round(value)}${suffix}`;
}

/** A numeric value for geometry, with an explicit fallback for layout only. */
export function plot(value: number | null | undefined, fallback = 0): number {
  return value == null || !Number.isFinite(value) ? fallback : value;
}

/** True when every listed value is present. */
export function allPresent(...values: (number | null | undefined)[]): boolean {
  return values.every((v) => v != null && Number.isFinite(v));
}
