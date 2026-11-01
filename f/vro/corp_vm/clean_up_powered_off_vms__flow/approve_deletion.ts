// vRO item3 "Approve deletion" (type: input, a user interaction).
// The interaction showed `vms` and collected `approved` (boolean) and `approver` (string).
// In Windmill this step suspends the flow (see `suspend` in flow.yaml); the resume form holds the same two fields.
import * as wmill from "windmill-client";

export async function main(vms: { id: string; name: string }[]) {
  const urls = await wmill.getResumeUrls();
  console.log(`Approval requested to delete ${vms.length} VMs: ${vms.map((vm) => vm.name).join(", ")}`);
  return { vms, ...urls };
}
