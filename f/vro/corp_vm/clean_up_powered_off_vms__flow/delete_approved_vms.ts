// vRO item4 "Delete approved VMs" (scriptable task).
// In bindings: vms, approved, approver. Out binding: deleted.
//
// Original script:
//   deleted = [];
//   if (!approved) {
//     System.warn("Deletion rejected by " + approver);
//   } else {
//     for (var i in vms) {
//       deleted.push(System.getModule("com.corp.vm").deleteVm(vms[i]));
//     }
//   }
//
// vsphere and dry_run are added: deleteVm needs the vCenter connection, and dry_run is passed down.
import { main as deleteVm } from "/f/vro/com_corp_vm/delete_vm";

type VmwareVsphere = { server: string; username: string; password: string; allow_unverified_ssl?: boolean };

export async function main(
  vms: { id: string; name: string }[],
  approved: boolean,
  approver: string,
  vsphere: VmwareVsphere,
  dry_run: boolean = false,
): Promise<string[]> {
  const deleted: string[] = [];
  if (!approved) {
    console.warn("Deletion rejected by " + approver);
  } else {
    // Sequential, like the vRO loop: the first failure stops the step.
    for (const vm of vms) {
      deleted.push(await deleteVm(vsphere, vm.id, dry_run));
    }
  }
  return deleted;
}
