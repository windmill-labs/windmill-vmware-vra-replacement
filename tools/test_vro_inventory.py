"""Tests for vro_inventory.py against a synthetic .package in vRO's on-disk format:
elements/<id>/{info (UTF-8 properties XML), data and categories (UTF-16BE with BOM)}.

  python3 tools/test_vro_inventory.py
"""

import csv
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vro_inventory as inv  # noqa: E402


def utf16be(text: str) -> bytes:
    return b"\xfe\xff" + text.encode("utf-16-be")


def info(elem_type: str, elem_id: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">\n'
        f'<properties><entry key="type">{elem_type}</entry><entry key="id">{elem_id}</entry></properties>'
    ).encode()


def categories(name: str) -> bytes:
    return utf16be(f'<?xml version="1.0" encoding="UTF-16"?><categories><category name="{name}"><name><![CDATA[{name}]]></name></category></categories>')


def workflow(wf_id: str, name: str, items: str, attribs: str = "") -> bytes:
    return utf16be(
        f'<?xml version="1.0" encoding="UTF-16"?>'
        f'<ns2:workflow xmlns:ns2="http://vmware.com/vco/workflow" root-name="item1" id="{wf_id}" version="1.0.0">'
        f"<display-name><![CDATA[{name}]]></display-name>{attribs}"
        f'<workflow-item name="item0" type="end" end-mode="0"/>{items}</ns2:workflow>'
    )


def task(script: str, extra: str = "") -> str:
    return f'<workflow-item name="t" out-name="item0" type="task" {extra}><script encoded="false"><![CDATA[{script}]]></script></workflow-item>'


def action(act_id: str, name: str, script: str, result_type: str = "string", runtime: str = "") -> bytes:
    rt = f"<runtime><![CDATA[{runtime}]]></runtime>" if runtime else ""
    return utf16be(
        f'<?xml version="1.0" encoding="UTF-16"?>'
        f'<dunes-script-module name="{name}" result-type="{result_type}" api-version="6.0.0" id="{act_id}" version="1.0.0">'
        f'{rt}<param n="vmName" t="string"><![CDATA[]]></param>'
        f'<script encoded="false"><![CDATA[{script}]]></script></dunes-script-module>'
    )


CONFIG = utf16be(
    '<?xml version="1.0" encoding="UTF-16"?><config-element id="c1" version="1.0.0">'
    "<display-name><![CDATA[vcenter_settings]]></display-name><atts>"
    '<att name="host" type="string" read-only="false"/><att name="password" type="SecureString" read-only="false"/>'
    "</atts></config-element>"
)

LONG_LOGIC = "\n".join(f"var step{i} = compute({i});" for i in range(8))


def build_package(path: Path) -> None:
    elements = {
        # plain logic, several lines -> convert
        "w1": ("Workflow", "com.corp.network", workflow("w1", "Allocate IP", task(LONG_LOGIC) + task("System.getModule(\"com.corp.util\").formatName(vmName);"))),
        # same as w1 with different literals -> merge
        "w2": ("Workflow", "com.corp.network", workflow("w2", "Allocate IP (copy)", task(LONG_LOGIC.replace("compute(", "compute(").replace("(1)", "(99)")) + task("System.getModule(\"com.corp.util\").formatName(vmName);"))),
        # one short step -> wrapper
        "w3": ("Workflow", "com.corp.vm", workflow("w3", "Power on", task("vm.powerOnVM_Task();"))),
        # plugin types -> rebuild
        "w4": ("Workflow", "com.corp.vm", workflow(
            "w4", "Clone VM",
            task(LONG_LOGIC + "\nvar vms = VcPlugin.getAllVirtualMachines(null, 'xpath:name');") + task("var x = 1;\nvar y = 2;"),
            attribs='<attrib name="template" type="VC:VirtualMachine"/>',
        )),
        # never run in the runs file -> retire (when runs given)
        "w5": ("Workflow", "com.corp.legacy", workflow("w5", "Old report", task(LONG_LOGIC + "\nvar z = 3;"))),
        "a1": ("ScriptModule", "com.corp.util", action("a1", "formatName", "return vmName.toLowerCase();")),
        "a2": ("ScriptModule", "com.corp.util", action("a2", "unusedHelper", "return 1;")),
        "a3": ("ScriptModule", "com.corp.util", action("a3", "findVm", "return Server.findAllForType('VC:VirtualMachine');", result_type="Array/VC:VirtualMachine")),
        "c1": ("ConfigurationElement", "com.corp.config", CONFIG),
    }
    # a3 is referenced through an action element inside a workflow
    elements["w6"] = ("Workflow", "com.corp.vm", workflow(
        "w6", "Find and tag",
        '<workflow-item name="a" out-name="item0" type="task" script-module="com.corp.util/findVm"><script encoded="false"><![CDATA[actionResult = System.getModule("com.corp.util").findVm(vmName);]]></script></workflow-item>'
        + task(LONG_LOGIC),
    ))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("dunes-meta-inf", "<properties/>")
        for elem_id, (elem_type, cat, data) in elements.items():
            z.writestr(f"elements/{elem_id}/info", info(elem_type, elem_id))
            z.writestr(f"elements/{elem_id}/categories", categories(cat))
            z.writestr(f"elements/{elem_id}/data", data)


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pkg = Path(self.tmp.name) / "com.corp.package"
        build_package(self.pkg)

    def tearDown(self):
        self.tmp.cleanup()

    def elements(self, runs=None):
        els = inv.read_path(self.pkg)
        inv.classify(els, runs, 365)
        return {e.name: e for e in els}

    def test_reads_all_element_types_from_utf16_package(self):
        els = self.elements()
        self.assertEqual(sum(e.type == "Workflow" for e in els.values()), 6)
        self.assertEqual(sum(e.type == "Action" for e in els.values()), 3)
        self.assertEqual(els["Allocate IP"].category, "com.corp.network")
        self.assertEqual(els["vcenter_settings"].attributes, {"host": "string", "password": "SecureString"})

    def test_workflow_verdicts(self):
        els = self.elements()
        self.assertEqual(els["Allocate IP"].verdict, "convert")
        self.assertEqual(els["Allocate IP (copy)"].verdict, "merge")
        self.assertEqual(els["Power on"].verdict, "wrapper")
        self.assertEqual(els["Clone VM"].verdict, "rebuild")
        self.assertIn("VC:VirtualMachine", els["Clone VM"].plugin_types)
        self.assertIn("VcPlugin", els["Clone VM"].plugin_types)

    def test_action_verdicts(self):
        els = self.elements()
        self.assertEqual(els["formatName"].verdict, "convert")
        self.assertEqual(els["unusedHelper"].verdict, "retire")
        self.assertEqual(els["findVm"].verdict, "rebuild")

    def test_runs_csv_retires_unused_workflows(self):
        runs_file = Path(self.tmp.name) / "runs.csv"
        with open(runs_file, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "last_run"])
            for wf in ("w1", "w2", "w3", "w4", "w6"):
                w.writerow([wf, "2099-01-01T00:00:00Z"])
            w.writerow(["w5", ""])
        els = self.elements(inv.load_runs(runs_file))
        self.assertEqual(els["Old report"].verdict, "retire")
        self.assertEqual(els["Old report"].reason, "never run")
        self.assertEqual(els["Allocate IP"].verdict, "convert")

    def test_cli_writes_report_and_json(self):
        out, js = Path(self.tmp.name) / "r.md", Path(self.tmp.name) / "r.json"
        self.assertEqual(inv.main([str(self.pkg), "--out", str(out), "--json", str(js)]), 0)
        md = out.read_text()
        self.assertIn("6 workflows, 3 actions, 1 configuration elements", md)
        self.assertIn("| VC:VirtualMachine |", md)
        self.assertIn('"verdict": "merge"', js.read_text())

    def test_extracted_directory_matches_package(self):
        extracted = Path(self.tmp.name) / "extracted"
        with zipfile.ZipFile(self.pkg) as z:
            z.extractall(extracted)
        els = inv.read_path(extracted)
        self.assertEqual(len([e for e in els if e.type == "Workflow"]), 6)


if __name__ == "__main__":
    unittest.main()
