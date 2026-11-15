"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { fmtNum } from "./ui";

interface Point {
  day: string;
  hours: string;
  flights: number;
}

/**
 * Daily flight hours, last 30 days. One series → no legend (the card title
 * names it). Thin bars with rounded tops, a 2px gap between bars, a recessive
 * axis, per-bar hover tooltip, and a screen-reader table with the same data.
 */
export function FlightHoursChart({ data, days = 30 }: { data: Point[]; days?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  // Draw at the real pixel width (not a scaled viewBox) so axis text stays readable on phones.
  const boxRef = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(800);
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(280, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Fill missing days with zero so the time axis is continuous.
  const series = useMemo(() => {
    const byDay = new Map(data.map((d) => [d.day, d]));
    const out: { day: string; hours: number; flights: number }[] = [];
    const today = new Date();
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const key = d.toLocaleDateString("en-CA"); // YYYY-MM-DD in local time
      const p = byDay.get(key);
      out.push({ day: key, hours: p ? Number(p.hours) : 0, flights: p?.flights ?? 0 });
    }
    return out;
  }, [data, days]);

  const H = 180;
  const pad = { l: 32, r: 8, t: 8, b: 20 };
  const max = Math.max(10, ...series.map((s) => s.hours));
  const niceMax = Math.ceil(max / 10) * 10;
  const slot = (W - pad.l - pad.r) / series.length;
  const barW = Math.max(2, slot - 2); // 2px gap between bars
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / niceMax);
  const ticks = [0, niceMax / 2, niceMax];
  const h = hover !== null ? series[hover] : null;

  return (
    <div className="relative" ref={boxRef}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block" role="img" aria-label="Fleet flight hours per day, last 30 days">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={1} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize={10} fill="var(--muted)" className="tabular">
              {t}
            </text>
          </g>
        ))}
        {series.map((s, i) => {
          const x = pad.l + i * slot + 1;
          const top = y(s.hours);
          const height = y(0) - top;
          return (
            <g key={s.day} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* hit target is the full column, bigger than the bar itself */}
              <rect x={pad.l + i * slot} y={pad.t} width={slot} height={H - pad.t - pad.b} fill="transparent" />
              {height > 0 && (
                <path
                  d={`M${x},${y(0)} V${top + Math.min(4, height)} q0,-4 4,-4 H${x + barW - 4} q4,0 4,4 V${y(0)} Z`}
                  fill="var(--primary)"
                  opacity={hover === null || hover === i ? 1 : 0.45}
                />
              )}
            </g>
          );
        })}
        {[0, Math.floor(series.length / 2), series.length - 1].map((i) => (
          <text key={i} x={pad.l + i * slot + slot / 2} y={H - 4} textAnchor="middle" fontSize={10} fill="var(--muted)">
            {new Date(series[i].day).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}
          </text>
        ))}
      </svg>
      {h && hover !== null && (
        <div
          className="pointer-events-none absolute top-0 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs shadow-lg"
          style={{ left: `${((pad.l + hover * slot + slot / 2) / W) * 100}%`, transform: "translateX(-50%)" }}
        >
          <div className="font-medium">
            {new Date(h.day).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" })}
          </div>
          <div className="tabular text-muted">
            {fmtNum(h.hours)} h · {h.flights} flight{h.flights === 1 ? "" : "s"}
          </div>
        </div>
      )}
      {/* Tables ignore height/overflow, so the visually-hidden wrapper must be a div. */}
      <div className="sr-only">
      <table>
        <caption>Flight hours per day</caption>
        <tbody>
          {series.map((s) => (
            <tr key={s.day}>
              <td>{s.day}</td>
              <td>{s.hours} hours</td>
              <td>{s.flights} flights</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
