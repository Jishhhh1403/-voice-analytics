import { ChevronDown, ChevronRight, GitBranch, Layers3 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Spinner } from "../components/ui";
import { number } from "../lib/format";
import type { JourneyNode } from "../lib/types";
import { useFetch } from "../lib/useFetch";

type JourneyResponse = {
  version: string;
  run_id: string | null;
  tree: JourneyNode[];
  unmapped: { problem_count: number; evidence_count: number };
};

function TreeNode({
  node,
  depth,
  maxEvidence,
  expanded,
  toggle,
}: {
  node: JourneyNode;
  depth: number;
  maxEvidence: number;
  expanded: Set<string>;
  toggle: (id: string) => void;
}) {
  const hasChildren = node.children.length > 0;
  const isOpen = expanded.has(node.node_id);
  const width = maxEvidence ? Math.max(2, (node.evidence_count / maxEvidence) * 100) : 0;

  return (
    <>
      <tr className={node.node_type === "module" ? "journey-module-row" : ""}>
        <td>
          <div className="tree-cell" style={{ paddingLeft: `${depth * 22}px` }}>
            {hasChildren ? (
              <button className="tree-toggle" onClick={() => toggle(node.node_id)} aria-label="Toggle node">
                {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              </button>
            ) : (
              <span className="tree-spacer" />
            )}
            {node.node_type === "module" ? <Layers3 size={16} /> : <GitBranch size={14} />}
            <Link to={`/problems?journey=${node.node_id}`} className="tree-link">
              {node.display_name}
            </Link>
            <span className="tree-id">{node.node_id}</span>
          </div>
        </td>
        <td className="num">{number(node.problem_count)}</td>
        <td className="num">{number(node.evidence_count)}</td>
        <td>
          <div className="tree-bar">
            <span style={{ width: `${width}%` }} />
          </div>
        </td>
        <td>
          <Link to={`/problems?journey=${node.node_id}`} className="btn btn-ghost btn-small">
            Explore
          </Link>
        </td>
      </tr>
      {isOpen &&
        node.children.map((child) => (
          <TreeNode
            key={child.node_id}
            node={child}
            depth={depth + 1}
            maxEvidence={maxEvidence}
            expanded={expanded}
            toggle={toggle}
          />
        ))}
    </>
  );
}

export default function JourneyPage() {
  const { data, loading, error, reload } = useFetch<JourneyResponse>("/journey");
  const [expanded, setExpanded] = useState<Set<string>>(
    new Set(["authentication", "payments", "cards", "statements", "support", "navigation"]),
  );
  const toggle = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const maxEvidence = data ? Math.max(1, ...flatten(data.tree).map((node) => node.evidence_count)) : 1;
  const totals = data
    ? flatten(data.tree).filter((node) => node.node_type === "module")
    : [];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Journey explorer"
        title="Banking taxonomy coverage"
        subtitle="Versioned app/feature taxonomy with evidence volume at every node. Click into any journey to inspect the underlying problems."
        actions={data && <Badge tone="violet">Taxonomy v{data.version}</Badge>}
      />

      {error && <ErrorState message={error} onRetry={reload} />}
      {loading && !data && <Spinner />}

      {data && (
        <>
          <div className="module-grid">
            {totals.map((node) => (
              <Link to={`/problems?journey=${node.node_id}`} className="module-card" key={node.node_id}>
                <span className="module-icon">
                  <Layers3 size={18} />
                </span>
                <div>
                  <strong>{node.display_name}</strong>
                  <span>{node.description}</span>
                </div>
                <div className="module-counts">
                  <strong>{node.problem_count}</strong>
                  <span>problems</span>
                  <small>{node.evidence_count} evidence</small>
                </div>
              </Link>
            ))}
          </div>

          <Card
            title="Taxonomy tree"
            hint="Problem counts include child features. Evidence volume is the number of linked feedback spans."
            className="table-card"
          >
            <div className="table-wrap">
              <table className="journey-table">
                <thead>
                  <tr>
                    <th>Journey / feature</th>
                    <th className="num">Problems</th>
                    <th className="num">Evidence</th>
                    <th>Relative evidence</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.tree.map((node) => (
                    <TreeNode
                      key={node.node_id}
                      node={node}
                      depth={0}
                      maxEvidence={maxEvidence}
                      expanded={expanded}
                      toggle={toggle}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

        </>
      )}
      {data && data.tree.length === 0 && <EmptyState title="Taxonomy is empty" />}
    </div>
  );
}

function flatten(nodes: JourneyNode[]): JourneyNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)]);
}
