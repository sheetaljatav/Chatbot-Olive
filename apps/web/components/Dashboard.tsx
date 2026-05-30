"use client";

import useSWR from "swr";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { swrFetcher } from "@/lib/api";
import { cx } from "@/lib/cx";
import styles from "./Dashboard.module.css";

interface Summary {
  total: number;
  success: number;
  errors: number;
  cancelled: number;
  tokens: number;
  p50: number;
  p95: number;
  p99: number;
  error_rate: number;
}

interface TimePoint {
  bucket: string;
  requests: number;
  errors: number;
  p50: number;
  p95: number;
}

interface ModelRow {
  provider: string;
  model: string;
  requests: number;
  errors: number;
  p50: number;
  p95: number;
  prompt_tokens: number;
  completion_tokens: number;
}

const REFRESH_MS = 5000;
const WINDOW_MINUTES = 60;

/* Mirrors the --chart-* tokens in tokens.css (SVG attrs can't read CSS vars). */
const CHART = {
  grid: "rgba(255,255,255,0.06)",
  axis: "#6e7480",
  requests: "#6d6afc",
  p50: "#34d399",
  p95: "#f59e0b",
  errors: "#f87171",
  completion: "#9d6bff",
} as const;

export default function Dashboard() {
  const { data: summary } = useSWR<Summary>(
    `/metrics/summary?window=${WINDOW_MINUTES}`,
    swrFetcher,
    { refreshInterval: REFRESH_MS },
  );
  const { data: series } = useSWR<TimePoint[]>(
    `/metrics/timeseries?window=${WINDOW_MINUTES}`,
    swrFetcher,
    { refreshInterval: REFRESH_MS },
  );
  const { data: byModel } = useSWR<ModelRow[]>(
    `/metrics/by_model?window=${WINDOW_MINUTES}`,
    swrFetcher,
    { refreshInterval: REFRESH_MS },
  );

  const seriesFmt = (series || []).map((p) => ({
    ...p,
    bucket: new Date(p.bucket).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
  }));

  const errorRate = (summary?.error_rate ?? 0) * 100;
  const highError = errorRate > 5;

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>Observability</h1>
          <p className={styles.subtitle}>
            Inference metrics · last {WINDOW_MINUTES} minutes
          </p>
        </div>
        <span className={styles.live}>
          <span className={styles.liveDot} aria-hidden />
          Live · {REFRESH_MS / 1000}s
        </span>
      </header>

      <div className={styles.stats}>
        <Stat label="Requests" value={fmt(summary?.total)} accent="indigo" />
        <Stat
          label="Error rate"
          value={`${errorRate.toFixed(1)}%`}
          accent={highError ? "red" : "green"}
        />
        <Stat label="p95 latency" value={`${fmt(summary?.p95)} ms`} accent="amber" />
        <Stat label="Total tokens" value={fmt(summary?.tokens)} accent="violet" />
      </div>

      <div className={styles.grid}>
        <Panel title="Requests per minute" className={styles.spanWide}>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={seriesFmt} margin={chartMargin}>
              <defs>
                <linearGradient id="gReq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={CHART.requests} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={CHART.requests} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="bucket" {...axisProps} />
              <YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<ChartTooltip />} cursor={cursorStyle} />
              <Area
                type="monotone"
                dataKey="requests"
                stroke={CHART.requests}
                strokeWidth={2}
                fill="url(#gReq)"
              />
              <Area
                type="monotone"
                dataKey="errors"
                stroke={CHART.errors}
                strokeWidth={2}
                fillOpacity={0}
              />
            </AreaChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Latency p50 / p95" className={styles.spanWide}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={seriesFmt} margin={chartMargin}>
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="bucket" {...axisProps} />
              <YAxis {...axisProps} unit="ms" />
              <Tooltip content={<ChartTooltip unit="ms" />} cursor={cursorStyle} />
              <Line
                type="monotone"
                dataKey="p50"
                stroke={CHART.p50}
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="p95"
                stroke={CHART.p95}
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Tokens by model" className={styles.spanWide}>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={(byModel || []).map((r) => ({
                ...r,
                key: `${r.provider}/${r.model}`,
              }))}
              margin={chartMargin}
            >
              <CartesianGrid stroke={CHART.grid} vertical={false} />
              <XAxis dataKey="key" {...axisProps} />
              <YAxis {...axisProps} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Legend wrapperStyle={legendStyle} />
              <Bar
                dataKey="prompt_tokens"
                name="prompt"
                stackId="t"
                fill={CHART.requests}
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="completion_tokens"
                name="completion"
                stackId="t"
                fill={CHART.completion}
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Per-model breakdown" className={styles.spanWide}>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Model</th>
                  <th className={styles.num}>Requests</th>
                  <th className={styles.num}>Errors</th>
                  <th className={styles.num}>p50</th>
                  <th className={styles.num}>p95</th>
                  <th className={styles.num}>Tokens</th>
                </tr>
              </thead>
              <tbody>
                {(byModel || []).length === 0 ? (
                  <tr>
                    <td colSpan={7} className={styles.tableEmpty}>
                      No data yet — send a message to populate metrics.
                    </td>
                  </tr>
                ) : (
                  (byModel || []).map((r, i) => (
                    <tr key={i}>
                      <td>{r.provider}</td>
                      <td className={styles.mono}>{r.model}</td>
                      <td className={styles.num}>{r.requests}</td>
                      <td className={cx(styles.num, r.errors > 0 && styles.errCell)}>
                        {r.errors}
                      </td>
                      <td className={styles.num}>{r.p50} ms</td>
                      <td className={styles.num}>{r.p95} ms</td>
                      <td className={styles.num}>
                        {(r.prompt_tokens || 0) + (r.completion_tokens || 0)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* --- Presentational helpers --- */

function fmt(n: number | undefined): string {
  return (n ?? 0).toLocaleString();
}

const ACCENTS = {
  indigo: styles.accentIndigo,
  violet: styles.accentViolet,
  green: styles.accentGreen,
  amber: styles.accentAmber,
  red: styles.accentRed,
} as const;

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent: keyof typeof ACCENTS;
}) {
  return (
    <div className={cx(styles.stat, ACCENTS[accent])}>
      <span className={styles.statBar} aria-hidden />
      <div className={styles.statLabel}>{label}</div>
      <div className={styles.statValue}>{value}</div>
    </div>
  );
}

function Panel({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cx(styles.panel, className)}>
      <h2 className={styles.panelTitle}>{title}</h2>
      {children}
    </section>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className={styles.tooltip}>
      <div className={styles.tooltipLabel}>{label}</div>
      {payload.map((p) => (
        <div key={p.name} className={styles.tooltipRow}>
          <span className={styles.tooltipKey}>
            <span
              className={styles.tooltipSwatch}
              style={{ background: p.color }}
            />
            {p.name}
          </span>
          <span className={styles.tooltipVal}>
            {p.value?.toLocaleString()}
            {unit ? ` ${unit}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

const chartMargin = { top: 8, right: 8, left: -12, bottom: 0 };
const axisProps = {
  stroke: CHART.axis,
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;
const cursorStyle = { stroke: "rgba(255,255,255,0.14)", strokeWidth: 1 };
const legendStyle = { fontSize: 12, paddingTop: 8 };
