"""In-process reader for the Graphify code graph (graphify-out/graph.json).

Zero third-party deps: works wherever the artifacts exist, even without the
`graphify` package installed (CI, a box with only the committed output). Loads
the ~1MB JSON once per process (cached) so neighbour lookups stay <50ms.

Re-extraction (rebuild) is delegated to the `graphify` binary — this module
never re-implements the AST extractor, only reads what it produced.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Optional

from ..config import PROJECT_ROOT


def graph_path() -> Path:
    """Location of graph.json — EQR_GRAPH_PATH override, else graphify-out/graph.json."""
    p = os.environ.get("EQR_GRAPH_PATH")
    return Path(p).expanduser().resolve() if p else PROJECT_ROOT / "graphify-out" / "graph.json"


@dataclass(frozen=True)
class Neighbor:
    node_id: str
    label: str
    relation: str
    direction: str          # "out" (this -> other) or "in" (other -> this)
    source_file: str
    source_location: str


class GraphifyReader:
    """Loads graph.json once and answers neighbour / hub / staleness questions."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or graph_path()

    # ---- loading ---------------------------------------------------------
    @cached_property
    def _g(self) -> dict:
        if not self.path.exists():
            raise FileNotFoundError(
                f"no code graph at {self.path} — run `eqr graph rebuild` (or `graphify update .`)")
        return json.loads(self.path.read_text())

    @cached_property
    def _nodes(self) -> dict[str, dict]:
        return {n["id"]: n for n in self._g["nodes"]}

    @cached_property
    def _by_label(self) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for n in self._g["nodes"]:
            for key in {n["label"], n.get("norm_label", n["label"]), n["id"]}:
                idx.setdefault(key.lower(), []).append(n["id"])
        return idx

    @cached_property
    def _container_ids(self) -> set[str]:
        """File/module nodes = sources of `contains` edges. Excluded from god nodes
        (they trivially touch every symbol they hold)."""
        return {l["source"] for l in self._g["links"] if l["relation"] == "contains"}

    # ---- stats -----------------------------------------------------------
    @property
    def stats(self) -> dict:
        g = self._g
        return {
            "nodes": len(g["nodes"]),
            "edges": len(g["links"]),
            "communities": len({n.get("community") for n in g["nodes"] if n.get("community") is not None}),
            "built_at_commit": g.get("built_at_commit"),
            "graph_mtime": self.path.stat().st_mtime,
        }

    def is_stale(self) -> Optional[bool]:
        """True if HEAD != built_at_commit. None if HEAD can't be resolved."""
        built = (self._g.get("built_at_commit") or "")[:8]
        if not built:
            return None
        try:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                                  capture_output=True, text=True, timeout=5).stdout.strip()[:8]
        except Exception:
            return None
        return bool(head) and head != built

    # ---- resolution & traversal -----------------------------------------
    def resolve(self, target: str) -> list[str]:
        """target may be a node id, a label ('rank_sleeve' / 'rank_sleeve()'),
        or a source_file ('eqr/strategy/rank.py'). Returns matching node ids."""
        t = target.lower()
        hits = self._by_label.get(t) or self._by_label.get(t + "()")
        if hits:
            return list(hits)
        return [n["id"] for n in self._g["nodes"] if n.get("source_file", "").lower() == t]

    def neighbors(self, node_id: str) -> list[Neighbor]:
        out: list[Neighbor] = []
        for l in self._g["links"]:
            if l["source"] == node_id:
                o = self._nodes.get(l["target"], {})
                out.append(Neighbor(l["target"], o.get("label", l["target"]), l["relation"],
                                    "out", o.get("source_file", ""), o.get("source_location", "") or ""))
            elif l["target"] == node_id:
                o = self._nodes.get(l["source"], {})
                out.append(Neighbor(l["source"], o.get("label", l["source"]), l["relation"],
                                    "in", o.get("source_file", ""), o.get("source_location", "") or ""))
        return out

    def god_nodes(self, top: int = 10) -> list[tuple[str, int]]:
        """Most-connected symbols (full degree, excluding file/module container
        nodes). Reproduces `graphify god-nodes`."""
        deg: dict[str, int] = {}
        for l in self._g["links"]:
            deg[l["source"]] = deg.get(l["source"], 0) + 1
            deg[l["target"]] = deg.get(l["target"], 0) + 1
        ranked = sorted(((nid, d) for nid, d in deg.items() if nid not in self._container_ids),
                        key=lambda kv: kv[1], reverse=True)
        return [(self._nodes.get(nid, {}).get("label", nid), d) for nid, d in ranked[:top]]

    def communities(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for n in self._g["nodes"]:
            if n.get("community") is None:
                continue
            name = n.get("community_name", f"Community {n.get('community')}")
            counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    # ---- LLM-context rendering ------------------------------------------
    def as_markdown(self, target: str, depth: int = 1) -> str:
        """Compact Markdown snippet for an LLM context window."""
        ids = self.resolve(target)
        if not ids:
            return f"_No node matching `{target}` in the code graph._"
        lines: list[str] = []
        for nid in ids[:5]:
            n = self._nodes[nid]
            lines.append(f"### `{n['label']}` — {n.get('source_file', '?')}:{n.get('source_location', '?')} "
                         f"· community _{n.get('community_name')}_")
            grouped: dict[str, list[str]] = {}
            for nb in self.neighbors(nid):
                arrow = "→" if nb.direction == "out" else "←"
                grouped.setdefault(f"{arrow} {nb.relation}", []).append(
                    f"`{nb.label}` ({nb.source_file}:{nb.source_location})")
            for rel, items in sorted(grouped.items()):
                lines.append(f"- **{rel}**: " + ", ".join(items[:12]))
        return "\n".join(lines)


def rebuild(no_cluster: bool = False) -> int:
    """Delegate re-extraction to the graphify binary. Returns its exit code."""
    import shutil
    exe = shutil.which("graphify")
    if not exe:
        raise RuntimeError("graphify not on PATH — install with `graphify install` "
                           "or run the rebuild from a shell that has it.")
    cmd = [exe, "update", str(PROJECT_ROOT)] + (["--no-cluster"] if no_cluster else [])
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode
