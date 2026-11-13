import {
  BookOpenCheck,
  BrainCircuit,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Database,
  Gauge,
  GitBranch,
  Layers3,
  Menu,
  Network,
  ShieldAlert,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useFetch } from "../lib/useFetch";

type Meta = {
  provider: string;
  taxonomy_version: string;
  code_version: string;
  schema_version: string;
  synthetic_warning: string;
  default_source?: { uri?: string; generation?: string };
  latest_completed_run?: { run_id: string } | null;
};

const navigation = [
  { to: "/", label: "Journey explorer", icon: GitBranch },
  { to: "/problems", label: "Customer problems", icon: ShieldAlert },
  { to: "/themes", label: "Theme map", icon: Network },
  { to: "/dimensions", label: "Factor analysis", icon: Layers3 },
  { to: "/portfolio", label: "Portfolio narrative", icon: BrainCircuit },
  { to: "/backlog", label: "Backlog validation", icon: UploadCloud },
];

export default function Layout() {
  const [open, setOpen] = useState(true);
  const [mobile, setMobile] = useState(false);
  const { data: meta } = useFetch<Meta>("/meta/source");

  return (
    <div className={`app-shell ${open ? "sidebar-open" : "sidebar-collapsed"}`}>
      <aside className={`sidebar ${mobile ? "mobile-visible" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <Database size={20} />
          </div>
          {open && (
            <div className="brand-copy">
              <strong>Customer Intelligence</strong>
              <span>Banking PoV workspace</span>
            </div>
          )}
          <button className="icon-btn mobile-only" onClick={() => setMobile(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>

        <nav className="nav">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                onClick={() => setMobile(false)}
                title={item.label}
              >
                <Icon size={18} />
                {open && <span>{item.label}</span>}
              </NavLink>
            );
          })}
        </nav>

        {open && (
          <div className="sidebar-panel">
            <div className="sidebar-panel-title">
              <Sparkles size={14} />
              Active intelligence
            </div>
            <div className="sidebar-kv">
              <span>Provider</span>
              <strong>{meta?.provider || "rules-v1"}</strong>
            </div>
            <div className="sidebar-kv">
              <span>Taxonomy</span>
              <strong>v{meta?.taxonomy_version || "1.0.0"}</strong>
            </div>
            <div className="sidebar-kv">
              <span>Schema</span>
              <strong>{meta?.schema_version || "1.0.0"}</strong>
            </div>
            <div className="sidebar-kv">
              <span>Storage</span>
              <strong>local://</strong>
            </div>
          </div>
        )}

        <button className="collapse-btn" onClick={() => setOpen((value) => !value)}>
          {open ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
          {open && <span>Collapse</span>}
        </button>
      </aside>

      {mobile && <div className="scrim" onClick={() => setMobile(false)} />}

      <div className="main-shell">
        <header className="topbar">
          <button className="icon-btn mobile-only" onClick={() => setMobile(true)} aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <div className="topbar-context">
            <span className="status-dot" />
            Local-first environment
            <span className="topbar-sep">/</span>
            <BookOpenCheck size={14} />
            Evidence-traceable analytics
          </div>
          <div className="topbar-right">
            <span className="version-pill">v{meta?.code_version || "0.1.0"}</span>
            <span className="mode-pill">
              <ClipboardCheck size={14} />
              {meta?.latest_completed_run ? "Analytics ready" : "Pipeline starting"}
            </span>
          </div>
        </header>

        <div className="synthetic-banner">
          <Gauge size={16} />
          <span>
            <strong>Synthetic data warning.</strong>{" "}
            {meta?.synthetic_warning ||
              "The bundled feedback is generated for testing, not real customer data."}
          </span>
        </div>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
