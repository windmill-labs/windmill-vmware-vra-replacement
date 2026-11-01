# Create or destroy one vSphere VM with OpenTofu (or Terraform).
#
# The HCL below is the whole module: one cloned VM, sized by the caller.
# State lives in Postgres (the `pg` backend), one OpenTofu workspace per VM,
# so concurrent requests for different VMs never share a state file.
#
# Worker requirement: the `tofu` (or `terraform`) binary on PATH. Bake it into
# the worker image or install it with a worker init script, and route this
# script to those workers with a worker tag (see README).

import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from typing import Literal, TypedDict


class c_vsphere(TypedDict):
    server: str
    user: str
    password: str
    allow_unverified_ssl: bool
    datacenter: str
    cluster: str
    datastore: str
    network: str
    folder: str
    domain: str


class postgresql(TypedDict):
    host: str
    port: int
    user: str
    dbname: str
    sslmode: str
    password: str


MAIN_TF = r"""
terraform {
  backend "pg" {}
  required_providers {
    vsphere = {
      source  = "vmware/vsphere"
      version = ">= 2.6.0"
    }
  }
}

variable "vsphere_server" {}
variable "vsphere_user" {}
variable "vsphere_password" { sensitive = true }
variable "allow_unverified_ssl" { default = false }
variable "datacenter" {}
variable "cluster" {}
variable "datastore" {}
variable "network" {}
variable "folder" { default = "" }
variable "domain" { default = "corp.local" }
variable "template" {}
variable "vm_name" {}
variable "cpus" { default = 2 }
variable "memory_mb" { default = 4096 }
variable "disk_gb" { default = 40 }
variable "annotation" { default = "" }

provider "vsphere" {
  vsphere_server       = var.vsphere_server
  user                 = var.vsphere_user
  password             = var.vsphere_password
  allow_unverified_ssl = var.allow_unverified_ssl
}

data "vsphere_datacenter" "dc" {
  name = var.datacenter
}

data "vsphere_compute_cluster" "cluster" {
  name          = var.cluster
  datacenter_id = data.vsphere_datacenter.dc.id
}

data "vsphere_datastore" "ds" {
  name          = var.datastore
  datacenter_id = data.vsphere_datacenter.dc.id
}

data "vsphere_network" "net" {
  name          = var.network
  datacenter_id = data.vsphere_datacenter.dc.id
}

data "vsphere_virtual_machine" "template" {
  name          = var.template
  datacenter_id = data.vsphere_datacenter.dc.id
}

resource "vsphere_virtual_machine" "vm" {
  name             = var.vm_name
  folder           = var.folder == "" ? null : var.folder
  resource_pool_id = data.vsphere_compute_cluster.cluster.resource_pool_id
  datastore_id     = data.vsphere_datastore.ds.id
  annotation       = var.annotation

  num_cpus  = var.cpus
  memory    = var.memory_mb
  guest_id  = data.vsphere_virtual_machine.template.guest_id
  scsi_type = data.vsphere_virtual_machine.template.scsi_type
  firmware  = data.vsphere_virtual_machine.template.firmware

  network_interface {
    network_id   = data.vsphere_network.net.id
    adapter_type = data.vsphere_virtual_machine.template.network_interface_types[0]
  }

  disk {
    label            = "disk0"
    size             = max(var.disk_gb, data.vsphere_virtual_machine.template.disks[0].size)
    thin_provisioned = data.vsphere_virtual_machine.template.disks[0].thin_provisioned
  }

  clone {
    template_uuid = data.vsphere_virtual_machine.template.id
    customize {
      linux_options {
        host_name = var.vm_name
        domain    = var.domain
      }
      network_interface {}
    }
  }
}

output "ip_address" {
  value = vsphere_virtual_machine.vm.default_ip_address
}

output "uuid" {
  value = vsphere_virtual_machine.vm.uuid
}

output "moid" {
  value = vsphere_virtual_machine.vm.moid
}
"""


def _pg_conn_str(pg: postgresql) -> str:
    user = urllib.parse.quote(pg["user"], safe="")
    password = urllib.parse.quote(pg.get("password") or "", safe="")
    sslmode = pg.get("sslmode") or "prefer"
    return f"postgres://{user}:{password}@{pg['host']}:{pg.get('port') or 5432}/{pg['dbname']}?sslmode={sslmode}"


def _run(binary: str, args: list[str], cwd: str, env: dict, capture: bool = False) -> str:
    # Logs stream to the Windmill job log as they are produced.
    print(f"$ {os.path.basename(binary)} {' '.join(args)}", flush=True)
    proc = subprocess.run(
        [binary, *args],
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return proc.stdout or ""


def main(
    action: Literal["apply", "destroy"],
    vm_name: str,
    vsphere: c_vsphere,
    tf_state: postgresql,
    template: str = "ubuntu-24.04-template",
    cpus: int = 2,
    memory_mb: int = 4096,
    disk_gb: int = 40,
    dry_run: bool = False,
) -> dict:
    if dry_run:
        print(f"[dry run] would {action} {vm_name} ({cpus} vCPU, {memory_mb} MB, {disk_gb} GB) from {template}")
        if action == "destroy":
            return {"vm_name": vm_name, "destroyed": True, "dry_run": True}
        return {
            "vm_name": vm_name,
            "ip_address": "10.0.0.42",
            "uuid": "00000000-0000-0000-0000-000000000000",
            "moid": "vm-0000",
            "dry_run": True,
        }

    binary = shutil.which("tofu") or shutil.which("terraform")
    if not binary:
        raise RuntimeError(
            "Neither `tofu` nor `terraform` is on PATH. Run this script on a worker "
            "group that has OpenTofu installed (see README: worker setup)."
        )

    workdir = tempfile.mkdtemp(prefix="tofu-")
    with open(os.path.join(workdir, "main.tf"), "w") as f:
        f.write(MAIN_TF)

    job_id = os.environ.get("WM_JOB_ID", "")
    workspace = os.environ.get("WM_WORKSPACE", "")
    env = {
        **os.environ,
        "TF_IN_AUTOMATION": "1",
        # pg backend: connection and schema come from the environment, never from a file.
        "PG_CONN_STR": _pg_conn_str(tf_state),
        "PG_SCHEMA_NAME": "windmill_vsphere_vms",
        "TF_VAR_vsphere_server": vsphere["server"],
        "TF_VAR_vsphere_user": vsphere["user"],
        "TF_VAR_vsphere_password": vsphere["password"],
        "TF_VAR_allow_unverified_ssl": json.dumps(bool(vsphere.get("allow_unverified_ssl", False))),
        "TF_VAR_datacenter": vsphere["datacenter"],
        "TF_VAR_cluster": vsphere["cluster"],
        "TF_VAR_datastore": vsphere["datastore"],
        "TF_VAR_network": vsphere["network"],
        "TF_VAR_folder": vsphere.get("folder") or "",
        "TF_VAR_domain": vsphere.get("domain") or "corp.local",
        "TF_VAR_template": template,
        "TF_VAR_vm_name": vm_name,
        "TF_VAR_cpus": str(cpus),
        "TF_VAR_memory_mb": str(memory_mb),
        "TF_VAR_disk_gb": str(disk_gb),
        "TF_VAR_annotation": f"Managed by Windmill ({workspace}), last job {job_id}",
    }
    flags = ["-input=false", "-no-color"]

    _run(binary, ["init", *flags], workdir, env)
    _run(binary, ["workspace", "select", "-or-create=true", vm_name], workdir, env)

    if action == "apply":
        _run(binary, ["apply", "-auto-approve", *flags], workdir, env)
        outputs = json.loads(_run(binary, ["output", "-json"], workdir, env, capture=True))
        return {
            "vm_name": vm_name,
            "ip_address": outputs["ip_address"]["value"],
            "uuid": outputs["uuid"]["value"],
            "moid": outputs["moid"]["value"],
            "dry_run": False,
        }

    _run(binary, ["destroy", "-auto-approve", *flags], workdir, env)
    _run(binary, ["workspace", "select", "default"], workdir, env)
    _run(binary, ["workspace", "delete", vm_name], workdir, env)
    return {"vm_name": vm_name, "destroyed": True, "dry_run": False}
