"""
Agent Map Graph Visualizer.
Generates PNG (matplotlib+networkx) and Mermaid (.mmd) visualizations
from an agent_map dict.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import networkx as nx


# ── Colour palette (matches dashboard dark theme) ──────────────────────────

BG_COLOR = "#0f1117"
TEXT_COLOR = "#e2e8f0"

NODE_COLORS = {
    "agent":                "#6366f1",
    "orchestrator":         "#3b82f6",
    "planner":              "#06b6d4",
    "tool_low":             "#22c55e",
    "tool_medium":          "#f97316",
    "tool_high":            "#ef4444",
    "memory_subsystem":     "#a855f7",
    "memory":               "#a855f7",
    "retrieval_subsystem":  "#06b6d4",
    "retrieval":            "#06b6d4",
}

EDGE_STYLES = {
    "invokes":  {"color": "#cbd5e1", "style": "-",  "width": 1.5},
    "requires": {"color": "#f97316", "style": "--", "width": 1.5},
    "contains": {"color": "#475569", "style": "-",  "width": 1.0},
    "uses":     {"color": "#38bdf8", "style": "-",  "width": 1.2},
    "delegates":{"color": "#38bdf8", "style": "-",  "width": 1.2},
}

# Layer assignment for multipartite layout
LAYER_MAP = {
    "agent": 0,
    "orchestrator": 1,
    "planner": 1,
    "tool": 2,
    "memory_subsystem": 3,
    "retrieval_subsystem": 3,
    "memory": 4,
    "retrieval": 4,
}


def _node_color(node_data: dict) -> str:
    ntype = node_data.get("type", "")
    if ntype == "tool":
        risk = node_data.get("risk_level", "low")
        return NODE_COLORS.get(f"tool_{risk}", NODE_COLORS["tool_low"])
    return NODE_COLORS.get(ntype, "#6b7280")


def _node_label(node_data: dict) -> str:
    ntype = node_data.get("type", "")
    if ntype == "agent":
        return "Agent"
    if ntype == "orchestrator":
        strategy = node_data.get("strategy", "")
        return f"Orchestrator\n{strategy}" if strategy else "Orchestrator"
    if ntype == "planner":
        return "Planner"
    if ntype == "tool":
        return node_data.get("name", node_data.get("id", "tool"))
    if ntype in ("memory_subsystem", "retrieval_subsystem"):
        return ntype.replace("_", " ").title()
    if ntype == "memory":
        return node_data.get("memory_type", "memory")
    if ntype == "retrieval":
        return node_data.get("implementation", "retrieval")
    return node_data.get("id", "?")


def _build_nx_graph(agent_map: dict) -> nx.DiGraph:
    """Reconstruct a NetworkX DiGraph from the agent_map['graph'] section."""
    g = nx.DiGraph()
    graph_data = agent_map.get("graph", {})
    for node in graph_data.get("nodes", []):
        nid = node["id"]
        g.add_node(nid, **{k: v for k, v in node.items() if k != "id"})
    for edge in graph_data.get("edges", []):
        g.add_edge(
            edge["source"], edge["target"],
            **{k: v for k, v in edge.items() if k not in ("source", "target")},
        )
    return g


# ── PNG Renderer ────────────────────────────────────────────────────────────

def _render_png(agent_map: dict, output_path: str) -> str:
    g = _build_nx_graph(agent_map)
    if not g.nodes:
        return output_path

    # Assign layers for multipartite layout
    for nid, data in g.nodes(data=True):
        ntype = data.get("type", "tool")
        data["subset"] = LAYER_MAP.get(ntype, 2)

    n_tools = sum(1 for _, d in g.nodes(data=True) if d.get("type") == "tool")
    fig_w = max(16, n_tools * 2.5)
    fig_h = max(10, 8 + n_tools * 0.3)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.axis("off")

    # Layout
    try:
        pos = nx.multipartite_layout(g, subset_key="subset", align="horizontal")
    except Exception:
        pos = nx.spring_layout(g, seed=42)

    # Normalize positions into [margin, 1-margin] range and flip y (layer 0 at top)
    if pos:
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        margin = 0.08
        for nid in pos:
            ox, oy = pos[nid]
            nx_ = margin + (ox - x_min) / (x_max - x_min) * (1 - 2 * margin) if x_max != x_min else 0.5
            ny_ = margin + (oy - y_min) / (y_max - y_min) * (1 - 2 * margin) if y_max != y_min else 0.5
            # Flip y so layer 0 is at top
            ny_ = 1 - ny_
            pos[nid] = (nx_, ny_)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Draw edges
    for src, tgt, edata in g.edges(data=True):
        rel = edata.get("relationship", "invokes")
        style_info = EDGE_STYLES.get(rel, EDGE_STYLES["invokes"])
        try:
            nx.draw_networkx_edges(
                g, pos, edgelist=[(src, tgt)], ax=ax,
                edge_color=style_info["color"],
                style="dashed" if style_info["style"] == "--" else "solid",
                width=style_info["width"],
                arrows=True, arrowsize=15,
                connectionstyle="arc3,rad=0.1",
                alpha=0.7,
                min_source_margin=30, min_target_margin=30,
            )
        except Exception:
            pass

    # Draw nodes as rounded-rect boxes
    for nid, data in g.nodes(data=True):
        if nid not in pos:
            continue
        x, y = pos[nid]
        color = _node_color(data)
        label = _node_label(data)
        ntype = data.get("type", "")

        font_size = 14 if ntype == "agent" else 10
        font_weight = "bold" if ntype in ("agent", "orchestrator") else "normal"

        # Box dimensions scale with label
        lines = label.split("\n")
        max_chars = max(len(l) for l in lines)
        box_w = max(0.10, max_chars * 0.009 + 0.03)
        box_h = max(0.05, len(lines) * 0.03 + 0.01)

        bbox = FancyBboxPatch(
            (x - box_w / 2, y - box_h / 2), box_w, box_h,
            boxstyle="round,pad=0.008",
            facecolor=color, edgecolor="white", linewidth=1.0, alpha=0.92,
            zorder=3,
        )
        ax.add_patch(bbox)

        text_color = "#000000" if color in ("#22c55e", "#f97316") else "#ffffff"
        ax.text(
            x, y, label,
            ha="center", va="center",
            fontsize=font_size, fontweight=font_weight,
            color=text_color, zorder=5,
        )

    # Title
    meta = agent_map.get("metadata", {})
    framework = meta.get("framework", "unknown")
    agent_name = meta.get("name", "Agent")
    title = f"{agent_name} ({framework}) — {n_tools} tools"
    ax.set_title(title, color=TEXT_COLOR, fontsize=16, fontweight="bold", pad=20)

    # Legend
    legend_items = [
        mpatches.Patch(color="#6366f1", label="Agent"),
        mpatches.Patch(color="#3b82f6", label="Orchestrator"),
        mpatches.Patch(color="#22c55e", label="Tool (low risk)"),
        mpatches.Patch(color="#f97316", label="Tool (medium risk)"),
        mpatches.Patch(color="#ef4444", label="Tool (high risk)"),
        mpatches.Patch(color="#a855f7", label="Memory"),
        mpatches.Patch(color="#06b6d4", label="Retrieval / Planner"),
    ]
    legend = ax.legend(
        handles=legend_items, loc="upper right",
        fontsize=8, facecolor="#1e293b", edgecolor="#334155",
        labelcolor=TEXT_COLOR, framealpha=0.9,
    )
    legend.get_frame().set_linewidth(0.5)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, facecolor=BG_COLOR, bbox_inches="tight", pad_inches=0.5)
    plt.close(fig)
    return output_path


# ── Mermaid Renderer ────────────────────────────────────────────────────────

def _mermaid_node_shape(ntype: str, nid: str, label: str) -> str:
    """Return Mermaid node declaration with appropriate shape."""
    safe = label.replace('"', "'").replace("\n", "<br/>")
    if ntype in ("agent", "orchestrator"):
        return f'  {nid}[[\"{safe}\"]]'
    if ntype == "tool":
        return f'  {nid}(\"{safe}\")'
    if ntype in ("memory_subsystem", "memory", "retrieval_subsystem", "retrieval"):
        return f'  {nid}[(\"{safe}\")]'
    if ntype == "planner":
        return f'  {nid}[[\"{safe}\"]]'
    return f'  {nid}[\"{safe}\"]'


def _mermaid_class(ntype: str, risk: str = "low") -> str:
    if ntype == "agent":
        return "agentNode"
    if ntype == "orchestrator":
        return "orchNode"
    if ntype == "planner":
        return "plannerNode"
    if ntype == "tool":
        return {"low": "toolLow", "medium": "toolMed", "high": "toolHigh"}.get(risk, "toolLow")
    if ntype in ("memory_subsystem", "memory"):
        return "memNode"
    if ntype in ("retrieval_subsystem", "retrieval"):
        return "retNode"
    return "defaultNode"


def _render_mermaid(agent_map: dict, output_path: str) -> str:
    g = _build_nx_graph(agent_map)
    if not g.nodes:
        Path(output_path).write_text("graph TD\n  empty[\"No nodes\"]\n")
        return output_path

    lines = ["graph TD"]

    # Node declarations
    for nid, data in g.nodes(data=True):
        ntype = data.get("type", "")
        label = _node_label(data)
        risk = data.get("risk_level", "low")
        cls = _mermaid_class(ntype, risk)
        lines.append(f"{_mermaid_node_shape(ntype, nid, label)}:::{cls}")

    lines.append("")

    # Edges
    for src, tgt, edata in g.edges(data=True):
        rel = edata.get("relationship", "invokes")
        if rel == "requires":
            lines.append(f"  {src} -.->|{rel}| {tgt}")
        elif rel in ("contains",):
            lines.append(f"  {src} --> {tgt}")
        else:
            lines.append(f"  {src} -->|{rel}| {tgt}")

    # Memory / retrieval subgraphs
    mem_nodes = [nid for nid, d in g.nodes(data=True) if d.get("type") == "memory"]
    ret_nodes = [nid for nid, d in g.nodes(data=True) if d.get("type") == "retrieval"]

    if mem_nodes:
        lines.append("")
        lines.append("  subgraph Memory")
        for nid in mem_nodes:
            lines.append(f"    {nid}")
        lines.append("  end")

    if ret_nodes:
        lines.append("")
        lines.append("  subgraph Retrieval")
        for nid in ret_nodes:
            lines.append(f"    {nid}")
        lines.append("  end")

    # Class definitions
    lines.append("")
    lines.append("  classDef agentNode fill:#6366f1,color:#fff,stroke:#818cf8")
    lines.append("  classDef orchNode fill:#3b82f6,color:#fff,stroke:#60a5fa")
    lines.append("  classDef plannerNode fill:#06b6d4,color:#fff,stroke:#22d3ee")
    lines.append("  classDef toolLow fill:#22c55e,color:#000,stroke:#4ade80")
    lines.append("  classDef toolMed fill:#f97316,color:#000,stroke:#fb923c")
    lines.append("  classDef toolHigh fill:#ef4444,color:#fff,stroke:#f87171")
    lines.append("  classDef memNode fill:#a855f7,color:#fff,stroke:#c084fc")
    lines.append("  classDef retNode fill:#06b6d4,color:#fff,stroke:#22d3ee")
    lines.append("  classDef defaultNode fill:#6b7280,color:#fff,stroke:#9ca3af")
    lines.append("")

    Path(output_path).write_text("\n".join(lines))
    return output_path


# ── Public API ──────────────────────────────────────────────────────────────

def visualize_agent_map(agent_map: dict, output_dir: str) -> tuple[str, str]:
    """
    Generate PNG and Mermaid visualizations of the agent map graph.

    Args:
        agent_map: The full agent map dictionary (must contain 'graph' key).
        output_dir: Directory where output files will be written.

    Returns:
        Tuple of (png_path, mermaid_path).
    """
    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, "agent_map_graph.png")
    mmd_path = os.path.join(output_dir, "agent_map_graph.mmd")

    _render_png(agent_map, png_path)
    _render_mermaid(agent_map, mmd_path)

    return png_path, mmd_path
