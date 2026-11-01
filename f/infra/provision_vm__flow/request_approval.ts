import * as wmill from "windmill-client";

// The flow suspends right after this step until someone approves or rejects.
// The links are printed to the job log and returned, so a later step, a Slack
// message or a ServiceNow work note can carry them to the approver.
export async function main(plan: any, ticket: string) {
  const urls = await wmill.getResumeUrls();
  console.log(`Approval needed for ${plan.vm_name} (${plan.approval_reason})`);
  console.log(`Approve or reject: ${urls.approvalPage}`);
  return {
    vm_name: plan.vm_name,
    reason: plan.approval_reason,
    ticket,
    approval_page: urls.approvalPage,
  };
}
