#!/usr/bin/env python3
"""Inventory a vRealize Orchestrator export and sort it for a Windmill migration.

Reads vRO content and writes a Markdown report (and optionally JSON) that sorts
every workflow and action into one of:

  retire    no run in the window you give (needs --runs), or an action nothing references
  merge     same structure and logic as another workflow, modulo literals
  wrapper   one meaningful step: becomes a single Windmill script, or disappears
  rebuild   uses plugin objects (VC:, AD:, REST:...): rewrite on the target's API or SDK
  convert   plain logic: port to a Windmill script or flow

Accepted inputs (files or directories, mixed freely):
  - .package files exported from the vRO client or Build Tools for VMware Aria
  - directories holding extracted packages (elements/<id>/info + data)
  - workflow / action XML files (Build Tools "xml" projects)

Standard library only. Nothing leaves the machine: run it where the export is.

  python3 tools/vro_inventory.py exports/*.package --out report.md --json report.json
  python3 tools/vro_inventory.py exports/ --runs runs.csv --since-days 365

runs.csv: one row per workflow, columns `id` or `name`, and `last_run` (ISO 8601,
empty when never run). Export it from the vRO REST API
(GET /vco/api/workflows/{id}/executions) or from vRO's database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLUGIN_TYPE = re.compile(r"^(?:Array/)?([A-Za-z][A-Za-z0-9_]*):([A-Za-z][A-Za-z0-9_]*)$")
SCRIPT_PLUGIN_REFS = re.compile(
    r"\b(VcPlugin|VraHost|VraEntitiesFinder|ActiveDirectory|SQLDatabaseManager|RESTHostManager|SSHSession|PowerShellHostManager|NSXConnectionManager|Server\.find\w*)\b"
)
GET_MODULE = re.compile(r"System\.getModule\(\s*[\"']([\w.]+)[\"']\s*\)\.(\w+)\s*\(")
STRING_LIT = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")
NUMBER_LIT = re.compile(r"\b\d+(?:\.\d+)?\b")
NON_STEP_ITEMS = {"end", "input", "waiting-event", "waiting-timer", "condition", "custom-condition", "switch", "foreach"}


@dataclass
class Element:
    id: str
    type: str
    name: str
    category: str = ""
    source: str = ""
    runtime: str = "javascript"
    item_types: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    linked_workflows: list[str] = field(default_factory=list)
    action_refs: list[str] = field(default_factory=list)
    plugin_types: set[str] = field(default_factory=set)
    attributes: dict[str, str] = field(default_factory=dict)
    verdict: str = ""
    reason: str = ""

    @property
    def script_lines(self) -> int:
        return sum(len([l for l in s.splitlines() if l.strip() and not l.strip().startswith("//")]) for s in self.scripts)

    @property
    def steps(self) -> int:
        return len([t for t in self.item_types if t not in NON_STEP_ITEMS])


# ---------------------------------------------------------------- decoding


def decode(raw: bytes) -> str:
    """vRO writes data and categories as UTF-16 with a BOM; info files are UTF-8."""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_xml(text: str) -> ET.Element | None:
    # ElementTree rejects an encoding declaration on an already decoded string.
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        elif isinstance(el.tag, str) and ":" in el.tag:
            el.tag = el.tag.split(":", 1)[1]
    return root


def parse_info(text: str) -> dict[str, str]:
    root = parse_xml(text)
    if root is None:
        return {}
    return {e.get("key", ""): (e.text or "").strip() for e in root.iter("entry")}


def parse_categories(text: str) -> str:
    root = parse_xml(text)
    if root is None:
        return ""
    names = [(c.findtext("name") or c.get("name") or "").strip() for c in root.iter("category")]
    return "/".join(n for n in names if n)


# ---------------------------------------------------------------- element parsers


def _collect_plugin_types(root: ET.Element, el: Element) -> None:
    for node in root.iter():
        for key in ("type", "t", "result-type"):
            m = PLUGIN_TYPE.match(node.get(key, "") or "")
            if m:
                el.plugin_types.add(f"{m.group(1)}:{m.group(2)}")


def _collect_script_refs(el: Element) -> None:
    for s in el.scripts:
        for m in SCRIPT_PLUGIN_REFS.finditer(s):
            ref = m.group(1)
            el.plugin_types.add("Server.find* (plugin object lookup)" if ref.startswith("Server.") else ref)
        for m in GET_MODULE.finditer(s):
            el.action_refs.append(f"{m.group(1)}/{m.group(2)}")


def element_from_xml(root: ET.Element, *, elem_id: str = "", elem_type: str = "", category: str = "", source: str = "") -> Element | None:
    tag = root.tag
    if tag == "workflow" or elem_type == "Workflow":
        el = Element(
            id=root.get("id", elem_id) or elem_id,
            type="Workflow",
            name=(root.findtext("display-name") or root.get("name") or elem_id).strip(),
            category=category,
            source=source,
        )
        for item in root.iter("workflow-item"):
            el.item_types.append(item.get("type", "unknown"))
            script = item.find("script")
            if script is not None and (script.text or "").strip():
                el.scripts.append(script.text)
            if item.get("linked-workflow-id"):
                el.linked_workflows.append(item.get("linked-workflow-id"))
            if item.get("script-module"):
                el.action_refs.append(item.get("script-module"))
        _collect_plugin_types(root, el)
        _collect_script_refs(el)
        return el

    if tag == "dunes-script-module" or elem_type == "ScriptModule":
        runtime = (root.findtext("runtime") or "javascript").strip().split(":")[0] or "javascript"
        el = Element(
            id=root.get("id", elem_id) or elem_id,
            type="Action",
            name=root.get("name", elem_id),
            category=category,
            source=source,
            runtime=runtime,
        )
        script = root.findtext("script")
        if script and script.strip():
            el.scripts.append(script)
        _collect_plugin_types(root, el)
        _collect_script_refs(el)
        return el

    if tag == "config-element" or elem_type == "ConfigurationElement":
        el = Element(
            id=root.get("id", elem_id) or elem_id,
            type="ConfigurationElement",
            name=(root.findtext("display-name") or root.get("name") or elem_id).strip(),
            category=category,
            source=source,
        )
        for att in root.iter("att"):
            el.attributes[att.get("name", "?")] = att.get("type", "?")
        _collect_plugin_types(root, el)
        return el

    return None


# ---------------------------------------------------------------- readers


def read_package_members(members: dict[str, bytes], source: str) -> list[Element]:
    """members: path inside the package -> bytes. Groups elements/<id>/{info,data,categories}."""
    by_id: dict[str, dict[str, bytes]] = defaultdict(dict)
    for path, raw in members.items():
        parts = path.replace("\\", "/").strip("/").split("/")
        if len(parts) >= 3 and parts[-3] == "elements":
            by_id[parts[-2]][parts[-1]] = raw
    out = []
    for elem_id, files in by_id.items():
        info = parse_info(decode(files["info"])) if "info" in files else {}
        elem_type = info.get("type", "")
        if elem_type in ("ResourceElement", "PolicyTemplate", "ActionEnvironment"):
            out.append(Element(id=elem_id, type=elem_type, name=elem_id, source=source))
            continue
        if "data" not in files:
            continue
        root = parse_xml(decode(files["data"]))
        if root is None:
            continue
        category = parse_categories(decode(files["categories"])) if "categories" in files else ""
        el = element_from_xml(root, elem_id=elem_id, elem_type=elem_type, category=category, source=source)
        if el:
            out.append(el)
    return out


def read_path(path: Path) -> list[Element]:
    if path.is_file() and (path.suffix in (".package", ".zip") or zipfile.is_zipfile(path)):
        with zipfile.ZipFile(path) as z:
            return read_package_members({n: z.read(n) for n in z.namelist() if not n.endswith("/")}, str(path))
    if path.is_file() and path.suffix == ".xml":
        if path.name.endswith(".element_info.xml"):
            return []
        root = parse_xml(decode(path.read_bytes()))
        # Build Tools "xml" projects keep id, type and category next to the element.
        info_file = path.with_name(path.stem + ".element_info.xml")
        info = parse_info(decode(info_file.read_bytes())) if info_file.exists() else {}
        category = info.get("categoryPath", path.parent.name)
        el = element_from_xml(root, elem_id=info.get("id", ""), elem_type=info.get("type", ""), category=category, source=str(path)) if root is not None else None
        return [el] if el else []
    if path.is_dir():
        found: list[Element] = []
        members = {}
        for dirpath, _, files in os.walk(path):
            for f in files:
                p = Path(dirpath) / f
                rel = p.relative_to(path).as_posix()
                if "/elements/" in f"/{rel}" and f in ("info", "data", "categories"):
                    members[rel] = p.read_bytes()
                elif p.suffix in (".package", ".xml"):
                    found.extend(read_path(p))
        if members:
            found.extend(read_package_members(members, str(path)))
        return found
    return []


# ---------------------------------------------------------------- classification


def fingerprint(el: Element) -> str:
    norm = []
    for s in el.scripts:
        s = STRING_LIT.sub('""', s)
        s = NUMBER_LIT.sub("0", s)
        norm.append(re.sub(r"\s+", " ", s).strip())
    payload = json.dumps([el.item_types, sorted(norm), sorted(el.action_refs)])
    return hashlib.sha1(payload.encode()).hexdigest()


def load_runs(path: Path) -> dict[str, datetime | None]:
    runs: dict[str, datetime | None] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row.get("id") or row.get("name") or "").strip()
            last = (row.get("last_run") or "").strip()
            when = None
            if last:
                when = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            runs[key] = when
    return runs


def classify(elements: list[Element], runs: dict[str, datetime | None] | None, since_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    workflows = [e for e in elements if e.type == "Workflow"]
    actions = [e for e in elements if e.type == "Action"]

    seen: dict[str, Element] = {}
    for wf in sorted(workflows, key=lambda w: (w.category, w.name)):
        if runs is not None:
            last = runs.get(wf.id, runs.get(wf.name, None))
            if last is None or last < cutoff:
                wf.verdict, wf.reason = "retire", "never run" if last is None else f"last run {last.date()}"
                continue
        fp = fingerprint(wf)
        if wf.steps > 0 and fp in seen:
            wf.verdict, wf.reason = "merge", f"same logic as '{seen[fp].name}'"
            continue
        seen.setdefault(fp, wf)
        if wf.steps <= 1 and wf.script_lines <= 5:
            wf.verdict, wf.reason = "wrapper", f"{wf.steps} step, {wf.script_lines} script lines"
        elif wf.plugin_types:
            wf.verdict, wf.reason = "rebuild", ", ".join(sorted(wf.plugin_types))
        else:
            wf.verdict, wf.reason = "convert", f"{wf.steps} steps, {wf.script_lines} script lines"

    referenced = set()
    for e in elements:
        for ref in e.action_refs:
            referenced.add(ref)
            referenced.add(ref.split("/")[-1])
    for a in actions:
        full = f"{a.category}/{a.name}" if a.category else a.name
        if a.name not in referenced and full not in referenced:
            a.verdict, a.reason = "retire", "not referenced by any workflow or action in this export"
        elif a.plugin_types:
            a.verdict, a.reason = "rebuild", ", ".join(sorted(a.plugin_types))
        else:
            a.verdict, a.reason = "convert", f"{a.runtime}, {a.script_lines} lines"


# ---------------------------------------------------------------- report

VERDICTS = ["retire", "merge", "wrapper", "rebuild", "convert"]
TARGET = {
    "retire": "Do not migrate",
    "merge": "One flow with an input for what differs",
    "wrapper": "One Windmill script, or call the tool directly",
    "rebuild": "Script on the vSphere API / SDK (OpenTofu, pyvmomi, govmomi, PowerCLI, REST)",
    "convert": "TypeScript, Python or PowerShell script; flow for multi-step workflows",
}


def md_table(head: list[str], rows: list[list]) -> str:
    esc = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def report(elements: list[Element], runs_given: bool, since_days: int) -> str:
    wfs = [e for e in elements if e.type == "Workflow"]
    acts = [e for e in elements if e.type == "Action"]
    confs = [e for e in elements if e.type == "ConfigurationElement"]
    other = Counter(e.type for e in elements if e.type not in ("Workflow", "Action", "ConfigurationElement"))

    out = ["# vRO migration inventory", ""]
    out.append(f"{len(wfs)} workflows, {len(acts)} actions, {len(confs)} configuration elements"
               + ("".join(f", {n} {t}" for t, n in sorted(other.items())) if other else "") + ".")
    if not runs_given:
        out.append("")
        out.append(f"No run history given (`--runs`), so no workflow is marked retire. Add it to find the ones unused for {since_days} days.")
    out += ["", "## Summary", ""]
    wc, ac = Counter(w.verdict for w in wfs), Counter(a.verdict for a in acts)
    out.append(md_table(["Verdict", "Workflows", "Actions", "Becomes"], [[v, wc.get(v, 0), ac.get(v, 0), TARGET[v]] for v in VERDICTS]))
    to_build = wc.get("convert", 0) + wc.get("rebuild", 0)
    out += ["", f"Workflows with logic of their own to migrate: {to_build} of {len(wfs)}."]

    plugins = Counter(p for e in wfs + acts for p in e.plugin_types)
    if plugins:
        out += ["", "## Plugin dependencies", "", "Each plugin is an integration to replace once and share across scripts.", ""]
        out.append(md_table(["Plugin type / object", "Used by"], [[p, n] for p, n in plugins.most_common()]))

    for title, items in (("Workflows", wfs), ("Actions", acts)):
        if not items:
            continue
        out += ["", f"## {title}", ""]
        rows = [[e.verdict, e.name, e.category, e.reason] for e in sorted(items, key=lambda e: (VERDICTS.index(e.verdict), e.category, e.name))]
        out.append(md_table(["Verdict", "Name", "Category", "Why"], rows))

    if confs:
        out += ["", "## Configuration elements", "", "Each becomes a Windmill resource; SecureString attributes become secret fields or variables.", ""]
        rows = [[c.name, c.category, len(c.attributes), sum(1 for t in c.attributes.values() if t == "SecureString")] for c in confs]
        out.append(md_table(["Name", "Category", "Attributes", "SecureStrings"], rows))

    out += ["", "## Limits", "",
            "- Action references are found statically (`System.getModule(...)` calls and action elements). Actions called dynamically show up as unreferenced.",
            "- Merge candidates match on step structure and scripts with literals removed. Review each group before merging.",
            "- Wrapper and convert are sized from script lines, not from what the scripts call."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help=".package files, extracted package directories or XML files")
    ap.add_argument("--runs", type=Path, help="CSV with id or name, and last_run")
    ap.add_argument("--since-days", type=int, default=365, help="retire workflows not run in this many days (default 365)")
    ap.add_argument("--out", type=Path, help="write the Markdown report here (default stdout)")
    ap.add_argument("--json", type=Path, help="also write every element and its verdict as JSON")
    args = ap.parse_args(argv)

    elements: list[Element] = []
    for p in args.paths:
        if not p.exists():
            print(f"not found: {p}", file=sys.stderr)
            return 2
        elements.extend(read_path(p))
    # The same element can sit in several packages: keep one.
    unique = {}
    for e in elements:
        unique.setdefault((e.type, e.id), e)
    elements = list(unique.values())
    if not elements:
        print("no vRO elements found in the given paths", file=sys.stderr)
        return 1

    runs = load_runs(args.runs) if args.runs else None
    classify(elements, runs, args.since_days)
    md = report(elements, runs is not None, args.since_days)
    if args.out:
        args.out.write_text(md)
    else:
        sys.stdout.write(md)
    if args.json:
        def ser(e: Element):
            d = asdict(e)
            d["plugin_types"] = sorted(e.plugin_types)
            d.pop("scripts")
            d["script_lines"] = e.script_lines
            d["steps"] = e.steps
            return d
        args.json.write_text(json.dumps([ser(e) for e in elements], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
