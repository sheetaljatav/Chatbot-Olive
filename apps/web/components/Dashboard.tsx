"use client";

import useSWR from "swr";
import {
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
    bucket: new Date(p.bucket).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  }));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-lg font-semibold">Dashboard · last {WINDOW_MINUTES}m</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Requests" value={summary?.total ?? 0} />
        <Stat
          label="Error rate"
          value={`${((summary?.error_rate ?? 0) * 100).toFixed(1)}%`}
          accent={(summary?.error_rate ?? 0) > 0.05 ? "red" : "default"}
        />
        <Stat label="p95 latency" value={`${summary?.p95 ?? 0} ms`} />
        <Stat label="Tokens" value={summary?.tokens ?? 0} />
      </div>

      <Panel title="Requests per minute">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={seriesFmt}>
            <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />
            <XAxis dataKey="bucket" stroke="#71717a" fontSize={12} />
            <YAxis stroke="#71717a" fontSize={12} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Line type="monotone" dataKey="requests" stroke="#3b82f6" dot={false} />
            <Line type="monotone" dataKey="errors" stroke="#ef4444" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Latency (p50 / p95)">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={seriesFmt}>
            <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />
            <XAxis dataKey="bucket" stroke="#71717a" fontSize={12} />
            <YAxis stroke="#71717a" fontSize={12} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Line type="monotone" dataKey="p50" stroke="#10b981" dot={false} />
            <Line type="monotone" dataKey="p95" stroke="#f59e0b" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Tokens by model">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={(byModel || []).map((r) => ({ ...r, key: `${r.provider}/${r.model}` }))}>
            <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />
            <XAxis dataKey="key" stroke="#71717a" fontSize={12} />
            <YAxis stroke="#71717a" fontSize={12} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend />
            <Bar dataKey="prompt_tokens" stackId="t" fill="#3b82f6" />
            <Bar dataKey="completion_tokens" stackId="t" fill="#10b981" />
          </BarChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Per-model breakdown">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-zinc-500 text-left">
                <th className="py-2 pr-4">Provider</th>
                <th className="py-2 pr-4">Model</th>
                <th className="py-2 pr-4">Requests</th>
                <th className="py-2 pr-4">Errors</th>
                <th className="py-2 pr-4">p50</th>
                <th className="py-2 pr-4">p95</th>
                <th className="py-2 pr-4">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {(byModel || []).map((r, i) => (
                <tr key={i} className="border-t border-zinc-800">
                  <td className="py-2 pr-4">{r.provider}</td>
                  <td className="py-2 pr-4">{r.model}</td>
                  <td className="py-2 pr-4">{r.requests}</td>
                  <td className="py-2 pr-4">{r.errors}</td>
                  <td className="py-2 pr-4">{r.p50} ms</td>
                  <td className="py-2 pr-4">{r.p95} ms</td>
                  <td className="py-2 pr-4">
                    {(r.prompt_tokens || 0) + (r.completion_tokens || 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function Stat({
  label,
  value,
  accent = "default",
}: {
  label: string;
  value: string | number;
  accent?: "default" | "red";
}) {
  return (
    <div className="border border-zinc-800 rounded-xl p-4">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div
        className={`mt-1 text-2xl font-semibold ${
          accent === "red" ? "text-red-400" : "text-zinc-100"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-zinc-800 rounded-xl p-4">
      <div className="text-sm font-medium mb-3">{title}</div>
      {children}
    </div>
  );
}

const tooltipStyle = {
  backgroundColor: "#0b0d10",
  border: "1px solid #27272a",
  borderRadius: 8,
  fontSize: 12,
};
