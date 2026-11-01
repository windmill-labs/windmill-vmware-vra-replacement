// Shared vSphere helper for scripts converted from vRO.
// Replaces the vRO vCenter plugin (VcPlugin, VC:* objects) with the
// vSphere Automation REST API (`/api/...`, vCenter 7.0 U2 and later).
//
// Import it from a converted action:
//   import { withSession, listVms, getVm, deleteVm } from "/f/vro/lib/vsphere";
//
// Not //native: allow_unverified_ssl needs Bun's `tls` fetch option.

export type VmwareVsphere = {
  server: string;
  username: string;
  password: string;
  allow_unverified_ssl?: boolean;
};

// Power states as returned by GET /api/vcenter/vm (vcenter.vm.power_state).
export type PowerState = "POWERED_ON" | "POWERED_OFF" | "SUSPENDED";

// Summary returned by GET /api/vcenter/vm.
export type VmSummary = {
  vm: string; // managed object id, e.g. vm-1234
  name: string;
  power_state: PowerState;
  cpu_count?: number;
  memory_size_MiB?: number;
};

// Subset of GET /api/vcenter/vm/{vm} used by the converted actions.
export type VmInfo = {
  name: string;
  power_state: PowerState;
};

export type Session = {
  base: string;
  token: string;
  request: (method: string, path: string, init?: RequestInit) => Promise<Response>;
};

function fetchOptions(vsphere: VmwareVsphere): Record<string, unknown> {
  // Bun-specific option to accept self-signed vCenter certificates.
  return vsphere.allow_unverified_ssl ? { tls: { rejectUnauthorized: false } } : {};
}

// Opens a vCenter session, runs `fn`, and always closes the session.
export async function withSession<T>(vsphere: VmwareVsphere, fn: (s: Session) => Promise<T>): Promise<T> {
  const base = `https://${vsphere.server}/api`;
  const extra = fetchOptions(vsphere);

  const login = await fetch(`${base}/session`, {
    method: "POST",
    headers: { Authorization: `Basic ${btoa(`${vsphere.username}:${vsphere.password}`)}` },
    ...extra,
  });
  if (!login.ok) throw new Error(`vCenter login failed: ${login.status} ${await login.text()}`);
  const token: string = await login.json();

  const request = (method: string, path: string, init: RequestInit = {}) =>
    fetch(`${base}${path}`, {
      ...init,
      method,
      headers: { ...(init.headers ?? {}), "vmware-api-session-id": token },
      ...extra,
    });

  try {
    return await fn({ base, token, request });
  } finally {
    await request("DELETE", "/session").catch(() => undefined);
  }
}

// GET /api/vcenter/vm with optional filters.
// TODO(vro): verify - vCenter returns an error instead of a partial list when more than 4000 VMs match the filter.
export async function listVms(s: Session, filter: { power_states?: PowerState[]; names?: string[] } = {}): Promise<VmSummary[]> {
  const q = new URLSearchParams();
  for (const p of filter.power_states ?? []) q.append("power_states", p);
  for (const n of filter.names ?? []) q.append("names", n);
  const qs = q.toString();
  const res = await s.request("GET", `/vcenter/vm${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`VM list failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

// GET /api/vcenter/vm/{vm}
export async function getVm(s: Session, vm: string): Promise<VmInfo> {
  const res = await s.request("GET", `/vcenter/vm/${encodeURIComponent(vm)}`);
  if (!res.ok) throw new Error(`VM ${vm} lookup failed: ${res.status} ${await res.text()}`);
  return await res.json();
}

// DELETE /api/vcenter/vm/{vm}. The VM must be powered off.
// Replaces destroy_Task() + vim3WaitTaskEnd(): the REST call returns when the deletion is done.
// TODO(vro): verify that DELETE /api/vcenter/vm/{vm} is synchronous on the vCenter version in use.
export async function deleteVm(s: Session, vm: string): Promise<void> {
  const res = await s.request("DELETE", `/vcenter/vm/${encodeURIComponent(vm)}`);
  if (!res.ok) throw new Error(`VM ${vm} delete failed: ${res.status} ${await res.text()}`);
}
