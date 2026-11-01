// Converted from vRO action com.corp.vm/deleteVm
// vRO id: 8a1f0c2e-1111-4a6b-9a01-0000000000a2 (version 1.0.3)
// Description: Destroys a powered-off VM and returns its name.
// Params: vm: VC:VirtualMachine (VM to destroy)   Returns: string
//
// Original source:
//   if (vm.runtime.powerState.value != "poweredOff") {
//     throw "Refusing to delete " + vm.name + ": it is not powered off";
//   }
//   var name = vm.name;
//   var task = vm.destroy_Task();
//   System.getModule("com.vmware.library.vc.basic").vim3WaitTaskEnd(task, false, 5);
//   System.log("Deleted " + name);
//   return name;
//
// VC:VirtualMachine becomes a vmware_vsphere resource plus the VM's managed object id (vm-1234).
// destroy_Task() + vim3WaitTaskEnd() become DELETE /api/vcenter/vm/{vm}, which returns when the VM is gone.

import { deleteVm, getVm, withSession, type VmwareVsphere } from "/f/vro/lib/vsphere";

export async function main(vsphere: VmwareVsphere, vm: string, dry_run: boolean = false): Promise<string> {
  if (dry_run) {
    // No call to vCenter in dry run, so the VM name is unknown: return the id in its place.
    console.log(`[dry run] would check that ${vm} is powered off, then DELETE /api/vcenter/vm/${vm}`);
    return vm;
  }

  return await withSession(vsphere, async (s) => {
    const info = await getVm(s, vm);
    if (info.power_state !== "POWERED_OFF") {
      throw new Error("Refusing to delete " + info.name + ": it is not powered off");
    }
    const name = info.name;
    await deleteVm(s, vm);
    console.log("Deleted " + name);
    return name;
  });
}
