// Dependency-free SVG sparkline (no chart lib) of the accumulated cost/token series.
export function CostSparkline({ series, width = 220, height = 44 }: { series: number[]; width?: number; height?: number }) {
  if (series.length < 2) {
    return <div className="h-11 text-xs text-muted">cost trend appears as the run progresses</div>;
  }
  const max = Math.max(...series);
  const min = Math.min(...series);
  const span = max - min || 1;
  const stepX = width / (series.length - 1);
  const points = series
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / span) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} role="img" aria-label="cost trend" className="overflow-visible">
      <polyline points={points} fill="none" stroke="#6366f1" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
