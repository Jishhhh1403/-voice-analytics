import { RefreshCcw, SlidersHorizontal } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { useFetch } from "../lib/useFetch";

type Options = {
  sources: string[];
  platforms: string[];
  journeys: { node_id: string; display_name: string; node_type: string }[];
  date_range: { min_date?: string; max_date?: string };
};

export default function FilterBar({ compact = false }: { compact?: boolean }) {
  const [params, setParams] = useSearchParams();
  const { data } = useFetch<Options>("/feedback/options");
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const active = ["start_date", "end_date", "source_type", "platform", "journey"].filter((key) => params.get(key));

  return (
    <div className={`filter-bar ${compact ? "compact" : ""}`}>
      <div className="filter-label">
        <SlidersHorizontal size={15} />
        Filters
        {active.length > 0 && <span className="filter-count">{active.length}</span>}
      </div>
      <label>
        <span>From</span>
        <input
          type="date"
          value={params.get("start_date") || ""}
          min={data?.date_range?.min_date?.slice(0, 10)}
          max={data?.date_range?.max_date?.slice(0, 10)}
          onChange={(event) => set("start_date", event.target.value)}
        />
      </label>
      <label>
        <span>To</span>
        <input
          type="date"
          value={params.get("end_date") || ""}
          min={data?.date_range?.min_date?.slice(0, 10)}
          max={data?.date_range?.max_date?.slice(0, 10)}
          onChange={(event) => set("end_date", event.target.value)}
        />
      </label>
      <label>
        <span>Source</span>
        <select value={params.get("source_type") || ""} onChange={(event) => set("source_type", event.target.value)}>
          <option value="">All sources</option>
          {data?.sources?.map((source) => (
            <option value={source} key={source}>
              {source.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Platform</span>
        <select value={params.get("platform") || ""} onChange={(event) => set("platform", event.target.value)}>
          <option value="">All platforms</option>
          {data?.platforms?.map((platform) => (
            <option value={platform} key={platform}>
              {platform}
            </option>
          ))}
        </select>
      </label>
      {!compact && (
        <label>
          <span>Journey</span>
          <select value={params.get("journey") || ""} onChange={(event) => set("journey", event.target.value)}>
            <option value="">All journeys</option>
            {data?.journeys
              ?.filter((journey) => journey.node_type === "module")
              .map((journey) => (
                <option value={journey.node_id} key={journey.node_id}>
                  {journey.display_name}
                </option>
              ))}
          </select>
        </label>
      )}
      {active.length > 0 && (
        <button
          className="btn btn-ghost btn-small"
          onClick={() => {
            const next = new URLSearchParams(params);
            active.forEach((key) => next.delete(key));
            setParams(next, { replace: true });
          }}
        >
          <RefreshCcw size={13} />
          Reset
        </button>
      )}
    </div>
  );
}
