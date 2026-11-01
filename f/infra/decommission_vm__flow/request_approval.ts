import * as wmill from "windmill-client";

export async function main(vm_name: string, ticket: string, reason: string) {
  const urls = await wmill.getResumeUrls();
  console.log(`Decommission of ${vm_name} requested (${reason || "no reason given"})`);
  console.log(`Approve or reject: ${urls.approvalPage}`);
  return { vm_name, ticket, reason, approval_page: urls.approvalPage };
}
