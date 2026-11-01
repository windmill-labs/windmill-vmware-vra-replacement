import * as wmill from "windmill-client";

// Runs when any step fails. If the VM was already created (the failure happened
// after provisioning), destroy it so a failed request leaves nothing behind,
// then record the outcome on the ServiceNow ticket.

const AFTER_PROVISION = new Set(["configure", "close_ticket", "summary"]);

export async function main(
  message: string,
  step_id: string,
  vm_name: string,
  ticket: string,
  rollback_on_failure: boolean,
  dry_run: boolean,
) {
  let rolledBack = false;
  if (rollback_on_failure && AFTER_PROVISION.has(step_id)) {
    console.log(`Rolling back ${vm_name} after failure in ${step_id}`);
    await wmill.runScriptByPath("f/infra/tofu_vm", {
      action: "destroy",
      vm_name,
      vsphere: "$res:f/infra/vsphere",
      placement: "$res:f/infra/vsphere_placement",
      tf_state: "$res:f/infra/tf_state",
      dry_run,
    });
    rolledBack = true;
  }

  if (ticket) {
    await wmill.runScriptByPath("f/infra/servicenow_update", {
      servicenow: "$res:f/infra/servicenow",
      number: ticket,
      work_notes: `Provisioning of ${vm_name} failed at step "${step_id}": ${message}.` +
        (rolledBack ? " The VM was destroyed." : ""),
      dry_run,
    });
  }

  return { failed_step: step_id, error: message, rolled_back: rolledBack };
}
