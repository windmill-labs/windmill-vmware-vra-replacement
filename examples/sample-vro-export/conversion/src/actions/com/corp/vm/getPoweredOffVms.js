// vRO action: com.corp.vm/getPoweredOffVms
// id: 8a1f0c2e-1111-4a6b-9a01-0000000000a1
// runtime: javascript
// returns: Array/VC:VirtualMachine
// param prefix: string  (VM name prefix, e.g. dev-)
// param minDaysOff: number  (Minimum days since power off)
// verdict: rebuild (VC:VirtualMachine, VcPlugin)
var vms = VcPlugin.getAllVirtualMachines(null, "xpath:name[starts-with(.,'" + prefix + "')]");
var cutoff = new Date();
cutoff.setDate(cutoff.getDate() - minDaysOff);
var result = [];
for (var i in vms) {
  var vm = vms[i];
  if (vm.runtime.powerState.value != "poweredOff") continue;
  var off = vm.runtime.bootTime; // vRO admins often (wrongly) use bootTime as the last state change
  if (off == null || off < cutoff) {
    result.push(vm);
  }
}
System.log("Found " + result.length + " VMs off for more than " + minDaysOff + " days");
return result;
