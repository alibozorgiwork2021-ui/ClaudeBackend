// Compact token count, mirroring claudebackend/cli.py::humantok (1_500_000 -> "1.50M").
export function humantok(n: number): string {
  if (n >= 1_000) {
    const thousands = Math.round(n / 1_000);
    if (thousands >= 1_000) return `${(n / 1e6).toFixed(2)}M`;
    return `${thousands}k`;
  }
  return String(n);
}

export function money(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "—";
  return `$${usd.toFixed(2)}`;
}

export function pct(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
