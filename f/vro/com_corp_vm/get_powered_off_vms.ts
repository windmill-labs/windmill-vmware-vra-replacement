// Converted from vRO action com.corp.vm/getPoweredOffVms
// vRO id: 8a1f0c2e-1111-4a6b-9a01-0000000000a1
// Params: prefix: string (VM name prefix, e.g. dev-), minDaysOff: number (Minimum days since power off)
// Returns: Array/VC:VirtualMachine
//
// Original source:
//   var vms = VcPlugin.getAllVirtualMachines(null, "xpath:name[starts-with(.,'" + prefix + "')]");
//   var cutoff = new Date();
//   cutoff.setDate(cutoff.getDate() - minDaysOff);
//   var result = [];
//   for (var i in vms) {
//     var vm = vms[i];
//     if (vm.runtime.powerState.value != "poweredOff") continue;
//     var off = vm.runtime.bootTime; // vRO admins often (wrongly) use bootTime as the last state change
//     if (off == null || off < cutoff) {
//       result.push(vm);
//     }
//   }
//   System.log("Found " + result.length + " VMs off for more than " + minDaysOff + " days");
//   return result;
//
// VcPlugin.getAllVirtualMachines becomes GET /api/vcenter/vm (vSphere Automation REST API).
// The returned VC:VirtualMachine objects become { id, name } with id the managed object id (vm-1234).
// Read-only: no dry_run argument.

import { listVms, withSession, type VmwareVsphere } from "/f/vro/lib/vsphere";

export async function main(vsphere: VmwareVsphere, prefix: string, minDaysOff: number): Promise<{ id: string; name: string }[]> {
  return await withSession(vsphere, async (s) => {
    // The xpath filter ran server side; the REST API has no name-prefix filter, so filter here.
    const vms = (await listVms(s)).filter((vm) => vm.name.startsWith(prefix));
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - minDaysOff);
    const result: { id: string; name: string }[] = [];
    for (const vm of vms) {
      if (vm.power_state !== "POWERED_OFF") continue;
      // NOTE(vro): the original compares runtime.bootTime with the cutoff. vSphere clears bootTime when a VM
      // powers off, so for powered-off VMs it is null and every powered-off VM matching the prefix is returned,
      // whatever minDaysOff says. That behavior is kept.
      // TODO(vro): verify - runtime.bootTime is not exposed by the vSphere Automation REST API, so `off` is
      // always null here. If some VMs in your estate do report a bootTime while powered off, read it with
      // pyvmomi or PowerCLI to reproduce the original exactly.
      const off: Date | null = bootTimeFromRest(vm);
      if (off == null || off < cutoff) {
        result.push({ id: vm.vm, name: vm.name });
      }
    }
    console.log("Found " + result.length + " VMs off for more than " + minDaysOff + " days");
    return result;
  });
}

function bootTimeFromRest(_vm: unknown): Date | null {
  return null;
}
