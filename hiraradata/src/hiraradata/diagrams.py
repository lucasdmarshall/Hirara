"""diagram_render: Graphviz DOT and Mermaid flowcharts to PNG / SVG.

Agents write diagrams as text well; they cannot turn that text into a
picture. Graphviz does the layout. Mermaid flowcharts (the subset agents
write most: nodes, shapes, labelled edges, subgraphs, directions) are
translated to DOT here, so no browser or Node runtime is needed.

Graphviz can read local files through attributes such as ``image``,
``shapefile`` and ``fontpath``, which would let a crafted diagram embed files
from the server into its output. Those attributes are refused, and Graphviz
runs with SERVER_NAME / GV_FILE_PATH set so it will not load images from
anywhere even if one slipped through.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile

from .config import DataConfig
from .errors import DataError

ENGINES = ("dot", "neato", "fdp", "circo", "twopi", "sfdp")
FORBIDDEN_ATTRS = re.compile(
    r"\b(image|imagepath|shapefile|fontpath|fontnames|stylesheet|imagescale)\s*=", re.I)


def check_dot(source: str) -> None:
    match = FORBIDDEN_ATTRS.search(source)
    if match:
        raise DataError(f"the {match.group(1)!r} attribute is not allowed (it can read "
                        "files on the server)")


# --- Mermaid flowchart -> DOT ----------------------------------------------------

_DIRS = {"TD": "TB", "TB": "TB", "BT": "BT", "LR": "LR", "RL": "RL"}
_SHAPES = [
    (r"\(\[(.+?)\]\)", "box", "rounded"),   # ([stadium])
    (r"\[\((.+?)\)\]", "cylinder", None),    # [(database)]
    (r"\(\((.+?)\)\)", "circle", None),      # ((circle))
    (r"\{\{(.+?)\}\}", "hexagon", None),     # {{hexagon}}
    (r"\[\[(.+?)\]\]", "box", "bold"),       # [[subroutine]]
    (r"\[/(.+?)/\]", "parallelogram", None),  # [/parallelogram/]
    (r"\[(.+?)\]", "box", None),             # [box]
    (r"\((.+?)\)", "box", "rounded"),        # (rounded)
    (r"\{(.+?)\}", "diamond", None),         # {decision}
    (r">(.+?)\]", "cds", None),              # >flag]
]
_NODE = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*(.*)$")
_EDGE = re.compile(
    r"\s*(-->|---|-\.->|-\.-|==>|===|--o|--x|<-->)\s*(?:\|([^|]*)\|)?\s*"
    r"|\s*--\s+([^-]+?)\s+(-->|---)\s*"
    r"|\s*==\s+([^=]+?)\s+(==>)\s*"
)


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_node(token: str, nodes: dict[str, dict]) -> str:
    m = _NODE.match(token.strip())
    if not m:
        raise DataError(f"cannot read node {token.strip()!r}")
    node_id, rest = m.group(1), m.group(2).strip()
    rest = re.sub(r":::\w+$", "", rest).strip()  # class shorthand
    spec = nodes.setdefault(node_id, {"label": node_id, "shape": "box", "style": "rounded"})
    if rest:
        for pattern, shape, style in _SHAPES:
            sm = re.fullmatch(pattern, rest)
            if sm:
                label = sm.group(1).strip().strip('"')
                spec.update(label=label, shape=shape, style=style)
                break
        else:
            raise DataError(f"unsupported node shape in {token.strip()!r}")
    return node_id


def mermaid_to_dot(source: str) -> str:
    lines = [ln.strip() for ln in source.strip().splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]
    if not lines:
        raise DataError("empty diagram")
    head = lines[0].split()
    if head[0] not in ("graph", "flowchart"):
        raise DataError(f"only Mermaid flowcharts (graph / flowchart) are supported, not {head[0]!r}; "
                        "use DOT for other diagrams")
    rankdir = _DIRS.get(head[1].upper(), "TB") if len(head) > 1 else "TB"
    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str, str | None, str]] = []
    clusters: list[tuple[str, list[str]]] = []
    stack: list[tuple[str, list[str]]] = []
    for line in lines[1:]:
        line = line.rstrip(";")
        low = line.lower()
        if low.startswith(("classdef", "class ", "style ", "linkstyle", "click ", "direction ")):
            continue
        if low.startswith("subgraph"):
            title = line[8:].strip() or f"group {len(clusters) + 1}"
            m = re.match(r"^([A-Za-z0-9_\-]+)\s*\[(.+)\]$", title)
            stack.append(((m.group(2) if m else title).strip('"'), []))
            continue
        if low == "end":
            if not stack:
                raise DataError("'end' without a matching subgraph")
            clusters.append(stack.pop())
            continue
        parts = _EDGE.split(line)
        # re.split with groups: [node, arrow, label, alt_label, alt_arrow, ..., node, ...]
        tokens, ops = [], []
        i = 0
        tokens.append(parts[0])
        i = 1
        while i < len(parts):
            arrow1, label1, label2, arrow2, label3, arrow3 = parts[i:i + 6]
            arrow = arrow1 or arrow2 or arrow3
            label = label1 if label1 is not None else (label2 or label3)
            ops.append((arrow, label.strip() if label else None))
            tokens.append(parts[i + 6])
            i += 7
        ids = []
        for tok in tokens:
            group = [t for t in tok.split("&") if t.strip()]
            ids.append([_parse_node(t, nodes) for t in group])
        for group in ids:
            if stack:
                stack[-1][1].extend(group)
        for (arrow, label), left, right in zip(ops, ids, ids[1:]):
            for a in left:
                for b in right:
                    edges.append((a, b, label, arrow))
    if stack:
        raise DataError("subgraph without 'end'")

    out = ["digraph G {", f"  rankdir={rankdir};",
           '  node [fontname="Helvetica", fontsize=12, color="#4C72B0", penwidth=1.4];',
           '  edge [fontname="Helvetica", fontsize=10, color="#555555"];']
    for k, (title, members) in enumerate(clusters):
        out.append(f"  subgraph cluster_{k} {{ label={_q(title)}; style=rounded; color=\"#999999\";")
        out.extend(f"    {_q(m)};" for m in dict.fromkeys(members))
        out.append("  }")
    for node_id, spec in nodes.items():
        style = f", style={_q(spec['style'])}" if spec.get("style") else ""
        out.append(f"  {_q(node_id)} [label={_q(spec['label'])}, shape={spec['shape']}{style}];")
    for a, b, label, arrow in edges:
        attrs = []
        if label:
            attrs.append(f"label={_q(label)}")
        if arrow in ("---", "-.-", "==="):
            attrs.append("arrowhead=none")
        if arrow.startswith("-."):
            attrs.append("style=dashed")
        if arrow.startswith("=="):
            attrs.append("penwidth=2.5")
        if arrow == "--o":
            attrs.append("arrowhead=odot")
        if arrow == "--x":
            attrs.append("arrowhead=tee")
        if arrow == "<-->":
            attrs.append("dir=both")
        out.append(f"  {_q(a)} -> {_q(b)}" + (f" [{', '.join(attrs)}]" if attrs else "") + ";")
    out.append("}")
    return "\n".join(out)


def render(source: str, *, language: str, fmt: str, engine: str, config: DataConfig) -> tuple[bytes, str]:
    if not source or not source.strip():
        raise DataError("source is required")
    if len(source) > config.max_source_chars:
        raise DataError(f"source is longer than HD_MAX_SOURCE_CHARS ({config.max_source_chars})")
    if fmt not in ("png", "svg"):
        raise DataError("format must be png or svg")
    if engine not in ENGINES:
        raise DataError(f"engine must be one of {', '.join(ENGINES)}")
    lang = (language or "auto").lower()
    if lang == "auto":
        first_line = source.lstrip().splitlines()[0]
        first = first_line.split(None, 1)[0].lower()
        # "graph" is a keyword in both; DOT always opens a brace on that line.
        mermaid_words = ("graph", "flowchart", "sequencediagram", "classdiagram", "gantt",
                         "statediagram", "erdiagram", "pie")
        lang = "mermaid" if first in mermaid_words and "{" not in first_line else "dot"
    if lang == "mermaid":
        dot = mermaid_to_dot(source)
    elif lang == "dot":
        dot = source
    else:
        raise DataError("language must be dot, mermaid or auto")
    check_dot(dot)
    with tempfile.TemporaryDirectory(prefix="hiraradata-gv-") as empty:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            # With SERVER_NAME set, Graphviz only loads images from GV_FILE_PATH.
            "SERVER_NAME": "hiraradata",
            "GV_FILE_PATH": empty,
            "HOME": empty,
        }
        try:
            proc = subprocess.run([config.dot, f"-K{engine}", f"-T{fmt}"], input=dot.encode(),
                                  capture_output=True, timeout=config.timeout, env=env, cwd=empty,
                                  check=False)
        except FileNotFoundError as exc:
            raise DataError("Graphviz is not installed (apt-get install graphviz) or set HD_DOT") from exc
        except subprocess.TimeoutExpired as exc:
            raise DataError(f"Graphviz timed out after {config.timeout:.0f}s") from exc
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise DataError("diagram error: " + (err[-1] if err else f"dot exited {proc.returncode}"))
    return proc.stdout, dot


__all__ = ["ENGINES", "check_dot", "mermaid_to_dot", "render"]
