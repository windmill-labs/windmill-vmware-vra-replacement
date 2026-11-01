// Runs only when the flow is started by a trigger (webhook, HTTP route, Kafka...).
// It maps a ServiceNow catalog request, sent by a business rule or Flow Designer
// REST step, to the flow inputs. Runs started from the Windmill form skip it.
//
// Expected body (shape it however you like on the ServiceNow side):
// { "number": "RITM0010001",
//   "variables": { "vm_name": "app-web-01", "size": "medium",
//                  "os": "ubuntu-24.04", "environment": "dev" } }

type Event = {
  kind: string;
  body: any;
  headers: Record<string, string>;
  query: Record<string, string>;
};

export async function preprocessor(event: Event) {
  const body = typeof event.body === "string" ? JSON.parse(event.body) : event.body ?? {};
  const v = body.variables ?? body;
  return {
    vm_name: String(v.vm_name ?? "").toLowerCase(),
    size: v.size ?? "small",
    os: v.os ?? "ubuntu-24.04",
    environment: v.environment ?? "dev",
    ticket: body.number ?? "",
    rollback_on_failure: true,
    dry_run: body.dry_run === true,
  };
}
