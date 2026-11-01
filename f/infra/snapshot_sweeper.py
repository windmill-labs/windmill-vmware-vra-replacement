# requirements:
# pyvmomi>=8.0

# Find VM snapshots older than max_age_days and delete them.
# Forgotten snapshots grow until they fill a datastore; this is the scheduled
# job that vRO admins usually kept as a cron-triggered workflow.
# dry_run defaults to true: the first runs only report.

import ssl
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from pyVim.connect import Disconnect, SmartConnect
from pyVim.task import WaitForTask
from pyVmomi import vim


class vmware_vsphere(TypedDict):
    server: str
    username: str
    password: str
    allow_unverified_ssl: bool


def _walk(tree, vm_name, out):
    for node in tree:
        out.append((vm_name, node))
        _walk(node.childSnapshotList, vm_name, out)


def main(
    vsphere: vmware_vsphere,
    max_age_days: int = 7,
    keep_if_name_contains: str = "keep",
    dry_run: bool = True,
) -> dict:
    ctx = ssl.create_default_context()
    if vsphere.get("allow_unverified_ssl"):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    si = SmartConnect(host=vsphere["server"], user=vsphere["username"], pwd=vsphere["password"], sslContext=ctx)
    try:
        content = si.RetrieveContent()
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        snapshots = []
        for vm in view.view:
            if vm.snapshot:
                _walk(vm.snapshot.rootSnapshotList, vm.name, snapshots)
        view.Destroy()

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        stale, kept = [], 0
        for vm_name, node in snapshots:
            if keep_if_name_contains and keep_if_name_contains.lower() in node.name.lower():
                kept += 1
                continue
            if node.createTime < cutoff:
                stale.append((vm_name, node))

        deleted = []
        for vm_name, node in stale:
            entry = {
                "vm": vm_name,
                "snapshot": node.name,
                "created": node.createTime.isoformat(),
                "age_days": (datetime.now(timezone.utc) - node.createTime).days,
            }
            if not dry_run:
                print(f"Deleting {vm_name} / {node.name}", flush=True)
                WaitForTask(node.snapshot.RemoveSnapshot_Task(removeChildren=False))
            deleted.append(entry)

        return {
            "dry_run": dry_run,
            "scanned": len(snapshots),
            "kept_by_name": kept,
            "stale": len(deleted),
            "snapshots": deleted,
        }
    finally:
        Disconnect(si)
