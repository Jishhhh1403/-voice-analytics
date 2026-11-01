import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { label } from "../lib/format";
import type { Summary } from "../lib/types";

const COLORS = ["#0f9f7a", "#4361ee", "#f59e0b", "#e4572e", "#7c3aed", "#64748b", "#0891b2", "#be185d"];

const SENTIMENT_COLORS: Record<string, string> = {
  negative: "#e4572e",
  mixed: "#f59e0b",
  neutral: "#94a3b8",
  positive: "#0f9f7a",
};

export function TrendChart({ data }: { data: Summary["trend"] }) {
  if (!data.length) return <div className="chart-empty">No trend data yet.</div>;
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ top: 10, right: 6, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#0f9f7a" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#0f9f7a" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
          <XAxis dataKey="period" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip
            contentStyle={{ borderRadius: 10, border: "1px solid #e5e7eb", fontSize: 12 }}
            labelStyle={{ fontWeight: 600 }}
          />
          <Area type="monotone" dataKey="total" name="Feedback" stroke="#0f9f7a" strokeWidth={2.2} fill="url(#trendFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SentimentJourneyChart({ data }: { data: Summary["sentiment_by_journey"] }) {
  const map = new Map<string, Record<string, number | string>>();
  for (const row of data) {
    const key = moduleLabel(row.journey_node_id);
    const entry = map.get(key) || { name: key };
    entry[row.sentiment] = Number(entry[row.sentiment] || 0) + row.total;
    map.set(key, entry);
  }
  const rows = Array.from(map.values()).sort((a, b) => {
    const total = (item: Record<string, number | string>) =>
      Number(item.negative || 0) + Number(item.positive || 0) + Number(item.neutral || 0) + Number(item.mixed || 0);
    return total(b) - total(a);
  });
  if (!rows.length) return <div className="chart-empty">No sentiment data yet.</div>;
  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
          <YAxis type="category" dataKey="name" width={128} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid #e5e7eb", fontSize: 12 }} />
          <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
          {(["negative", "mixed", "neutral", "positive"] as const).map((key) => (
            <Bar key={key} dataKey={key} stackId="sentiment" fill={SENTIMENT_COLORS[key]} radius={key === "positive" ? [0, 4, 4, 0] : 0} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SourceDonut({ data }: { data: Summary["source_mix"] }) {
  if (!data.length) return <div className="chart-empty">No source data yet.</div>;
  return (
    <div className="donut-wrap">
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={data} dataKey="total" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={2}>
            {data.map((_, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid #e5e7eb", fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
      <div className="legend-list">
        {data.map((item, index) => (
          <div key={item.name}>
            <span className="dot" style={{ background: COLORS[index % COLORS.length] }} />
            <span>{label(item.name)}</span>
            <strong>{item.total}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RatingBars({ data }: { data: Summary["rating_mix"] }) {
  if (!data.length) return <div className="chart-empty">No rating data yet.</div>;
  return (
    <div className="rating-bars">
      {data.map((item) => (
        <div className="rating-row" key={item.rating}>
          <span>{item.rating === "none" ? "No rating" : `${item.rating} star`}</span>
          <div className="rating-track">
            <span
              style={{
                width: `${(item.total / Math.max(...data.map((row) => row.total))) * 100}%`,
                background: item.rating === "none" ? "#94a3b8" : Number(item.rating) <= 2 ? "#e4572e" : "#0f9f7a",
              }}
            />
          </div>
          <strong>{item.total}</strong>
        </div>
      ))}
    </div>
  );
}

export function moduleLabel(nodeId?: string | null): string {
  if (!nodeId || nodeId === "unmapped") return "Unmapped";
  const map: Record<string, string> = {
    authentication: "Authentication",
    payments: "Payments",
    beneficiaries: "Beneficiaries",
    accounts: "Accounts",
    statements: "Statements",
    cards: "Cards",
    deposits: "Deposits",
    loans: "Loans",
    onboarding: "Onboarding / KYC",
    support: "Support & disputes",
    notifications: "Notifications",
    navigation: "Navigation & performance",
  };
  const root = nodeId.split(".")[0];
  return map[root] || nodeId.replace(/_/g, " ");
}
