// Port of a typical vRO action:
//
//   // Inputs: prefix (string)   Return type: Array/VC:VirtualMachine
//   var vms = VcPlugin.getAllVirtualMachines(null, "xpath:name[starts-with(.,'" + prefix + "')]");
//   var result = [];
//   for (var i in vms) {
//     if (vms[i].runtime.powerState.value == "poweredOff") result.push(vms[i]);
//   }
//   System.log("Found " + result.length + " powered-off VMs");
//   return result;
//
// The vCenter plugin object becomes a call to the vSphere Automation REST API
// (vCenter 7.0 U2 and later), and the configuration element becomes a vmware_vsphere resource.

type VmwareVsphere = {
  server: string;
  username: string;
  password: string;
};

export async function main(vsphere: VmwareVsphere, prefix: string = "") {
  const base = `https://${vsphere.server}/api`;

  const session = await fetch(`${base}/session`, {
    method: "POST",
    headers: { Authorization: `Basic ${btoa(`${vsphere.username}:${vsphere.password}`)}` },
  });
  if (!session.ok) throw new Error(`vCenter login failed: ${session.status}`);
  const token: string = await session.json();

  try {
    const res = await fetch(`${base}/vcenter/vm?power_states=POWERED_OFF`, {
      headers: { "vmware-api-session-id": token },
    });
    if (!res.ok) throw new Error(`VM list failed: ${res.status} ${await res.text()}`);
    const vms: { vm: string; name: string; cpu_count: number; memory_size_MiB: number }[] = await res.json();
    const result = vms.filter((vm) => vm.name.startsWith(prefix));
    console.log(`Found ${result.length} powered-off VMs`);
    return result;
  } finally {
    await fetch(`${base}/session`, { method: "DELETE", headers: { "vmware-api-session-id": token } });
  }
}
