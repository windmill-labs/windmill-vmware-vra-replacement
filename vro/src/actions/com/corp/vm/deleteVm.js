// vRO action: com.corp.vm/deleteVm
// id: 8a1f0c2e-1111-4a6b-9a01-0000000000a2
// runtime: javascript
// returns: string
// param vm: VC:VirtualMachine  (VM to destroy)
// verdict: rebuild (VC:VirtualMachine)
if (vm.runtime.powerState.value != "poweredOff") {
  throw "Refusing to delete " + vm.name + ": it is not powered off";
}
var name = vm.name;
var task = vm.destroy_Task();
System.getModule("com.vmware.library.vc.basic").vim3WaitTaskEnd(task, false, 5);
System.log("Deleted " + name);
return name;
