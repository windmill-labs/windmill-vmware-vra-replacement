// Add a work note to a ServiceNow record and optionally move its state.
// Works for any table (sc_req_item, change_request, incident...) using the Table API.
// The `servicenow` resource accepts either basic auth or an OAuth bearer token.

type Servicenow = {
  instance_url: string;
  username?: string;
  password?: string;
  token?: string;
};

function authHeader(sn: Servicenow): string {
  if (sn.token) return `Bearer ${sn.token}`;
  return `Basic ${btoa(`${sn.username ?? ""}:${sn.password ?? ""}`)}`;
}

export async function main(
  servicenow: Servicenow,
  number: string,
  work_notes: string,
  table: string = "sc_req_item",
  state: string = "",
  dry_run: boolean = false,
) {
  if (!number) return { skipped: true, reason: "no ticket number" };
  if (dry_run) {
    console.log(`[dry run] ${table} ${number}: ${work_notes}${state ? ` (state -> ${state})` : ""}`);
    return { number, table, updated: false, dry_run: true };
  }

  const base = servicenow.instance_url.replace(/\/$/, "");
  const headers = {
    Authorization: authHeader(servicenow),
    Accept: "application/json",
    "Content-Type": "application/json",
  };

  // Resolve the human-facing number (RITM0010001) to a sys_id.
  const lookup = await fetch(
    `${base}/api/now/table/${table}?sysparm_query=number=${encodeURIComponent(number)}&sysparm_fields=sys_id&sysparm_limit=1`,
    { headers },
  );
  if (!lookup.ok) throw new Error(`ServiceNow lookup failed: ${lookup.status} ${await lookup.text()}`);
  const sysId = (await lookup.json()).result?.[0]?.sys_id;
  if (!sysId) throw new Error(`${table} ${number} not found`);

  const body: Record<string, string> = { work_notes };
  if (state) body.state = state;
  const res = await fetch(`${base}/api/now/table/${table}/${sysId}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`ServiceNow update failed: ${res.status} ${await res.text()}`);
  return { number, table, sys_id: sysId, updated: true, dry_run: false };
}
