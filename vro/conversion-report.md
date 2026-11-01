# vRO conversion report

Source: `examples/sample-vro-export/` (Build Tools xml layout). Inventory: `vro/inventory.md`, `vro/inventory.json`. Extracted sources: `vro/src/`.

Inventory counts: 1 workflow, 2 actions, 1 configuration element. Verdicts: retire 0, merge 0, wrapper 0, rebuild 3 (1 workflow, 2 actions), convert 0. No `--runs` file was given, so nothing could be marked retire.
Plugin dependencies: `VC:VirtualMachine` (3 uses), `VcPlugin` (1 use), replaced by one shared helper, `f/vro/lib/vsphere.ts`.
Merge groups: none.

## Elements

| vRO element | Verdict | Windmill path | Status | Notes |
| --- | --- | --- | --- | --- |
| vCenter plugin (`VC:*`, `VcPlugin`) | shared helper | `f/vro/lib/vsphere.ts` | converted | vSphere Automation REST API (`/api/session`, `/api/vcenter/vm`). Exercised through the previews below. |
| `Corp/vcenter_cleanup` (configuration element) | resource | split: `vcHost` / `vcUser` / `vcPassword` → `f/vro/vsphere`; `notifyEmail` → `f/vro/corp/vcenter_cleanup.resource.yaml`, type `c_vcenter_cleanup` (`c_vcenter_cleanup.resource-type.yaml`) | needs resource | Connection attributes go into the Hub `vmware_vsphere` resource so the credentials exist once. Not referenced by any exported workflow or action. |
| vCenter connection used by the plugin | resource | `f/vro/vsphere.resource.yaml` (`vmware_vsphere`) | needs resource | Server and user from `vcenter_cleanup` (`vcHost`, `vcUser`); password empty. |
| `com.corp.vm/deleteVm` | rebuild | `f/vro/com_corp_vm/delete_vm.ts` | dry run passed | `destroy_Task` + `vim3WaitTaskEnd` → `DELETE /api/vcenter/vm/{vm}`. Takes `dry_run`. |
| `com.corp.vm/getPoweredOffVms` | rebuild | `f/vro/com_corp_vm/get_powered_off_vms.ts` | needs resource | `VcPlugin.getAllVirtualMachines` → `GET /api/vcenter/vm`, prefix filtered client side. Read-only, no `dry_run`. Preview reaches the vCenter login and fails on the fake host (502). |
| `Corp/VM/Clean up powered-off VMs` | rebuild | `f/vro/corp_vm/clean_up_powered_off_vms__flow` | needs resource | Steps `delete_approved_vms`, `approve_deletion` and `workflow_outputs` pass in step preview. The whole flow stops at step 1 without a vCenter. The false branch was checked with a temporary copy of the flow that mocked step 1 (returned `{"deleted": null}`), then deleted. |

## Item mapping for the workflow

| vRO item | Type | Flow module |
| --- | --- | --- |
| item1 getPoweredOffVms (start item, `root-name`) | task + action | `get_powered_off_vms`, `type: script`, path `f/vro/com_corp_vm/get_powered_off_vms` |
| item2 Anything to delete? | custom-condition | `anything_to_delete`, `branchone`, expr `results.get_powered_off_vms.length > 0`, empty default (alt_next = item0 end) |
| item3 Approve deletion | input | `approve_deletion`, rawscript with module-level `suspend` and a `resume_form` with `approved` (boolean) and `approver` (string) |
| item4 Delete approved VMs | scriptable task | `delete_approved_vms`, rawscript; `approved` / `approver` from `resume.*` |
| item0 | end | nothing |
| output `deleted` | workflow output | `workflow_outputs`, returns `{ deleted }`, `null` on the false path as in vRO |

## Decisions taken without asking (conservative choices)

1. Merge groups: none found, nothing to ask.
2. Configuration element `vcenter_cleanup`: split. Its connection attributes (`vcHost`, `vcUser`, `vcPassword`) are the `vmware_vsphere` resource `f/vro/vsphere`; `notifyEmail` stays in a `c_vcenter_cleanup` resource. One place for the credentials.
3. The vCenter connection behind the plugin objects is that same `f/vro/vsphere`, passed to scripts and the flow as the `vsphere` argument (flow default `$res:f/vro/vsphere`).
4. Paths: dots in categories become underscores, `/` in categories becomes `_`, categories and names are lowercased and snake_cased: `Corp/VM` + `Clean up powered-off VMs` → `f/vro/corp_vm/clean_up_powered_off_vms`, `Corp` → `f/vro/corp`.
5. Argument order: the connection (`vsphere`) comes first, then the vRO params in their order, then `dry_run`.
6. `getPoweredOffVms` is read-only, so it does not take `dry_run`. As a result, the flow's dry run still lists VMs in vCenter.
7. `deleteVm` in dry run makes no call to vCenter at all, so it cannot know the VM name. It returns the VM id in its place.
8. The approval keeps vRO's two form fields, `approved` and `approver`, rather than using Windmill's recorded approver identity (`approvers`). Windmill's Cancel button cancels the flow, whereas vRO's rejection path ran item4 with `approved = false` and logged a warning. Submitting the form with `approved` unchecked reproduces that path.
9. No approval timeout, approver group or notification were added: the export has none.
10. Script returns: `VC:VirtualMachine` becomes `{ id, name }`, with `id` the managed object id (`vm-1234`).

## Resources and secrets to create

| Path | Type | Fill in |
| --- | --- | --- |
| resource type `c_vcenter_cleanup` | custom | nothing: `c_vcenter_cleanup.resource-type.yaml` syncs with `wmill sync push` |
| `f/vro/corp/vcenter_cleanup` | `c_vcenter_cleanup` | nothing (`notifyEmail` is copied from vRO) |
| `f/vro/vsphere` | `vmware_vsphere` | `password`; check `server` and `username` against the vCenter registered in the vRO plugin; set `allow_unverified_ssl` if vCenter uses a self-signed certificate |

## TODO(vro)

- `f/vro/lib/vsphere.ts` `listVms`: check that `GET /api/vcenter/vm` returns an error rather than a partial list when more than 4000 VMs match. With no server-side prefix filter, all VMs are listed.
- `f/vro/lib/vsphere.ts` `deleteVm`: check that `DELETE /api/vcenter/vm/{vm}` returns only after the VM is deleted on your vCenter version (it replaces `destroy_Task` + `vim3WaitTaskEnd(task, false, 5)`).
- `f/vro/com_corp_vm/get_powered_off_vms.ts`: `runtime.bootTime` is not available in the vSphere Automation REST API, so `off` is always null. See the NOTE below. If you need the exact original comparison, read `bootTime` with pyvmomi or PowerCLI.

## NOTE(vro): quirks kept as-is

- `getPoweredOffVms` uses `runtime.bootTime` as the power-off date. vSphere clears `bootTime` on power off, so every powered-off VM that matches the prefix is returned, whatever `minDaysOff` is. The conversion keeps that behavior. In practice, the workflow offers to delete every powered-off VM with the prefix.
- `getPoweredOffVms` put `prefix` unescaped into an xpath string, so a prefix containing `'` broke the query in vRO. The REST version filters with `startsWith` and has no such failure. This is the one deliberate behavior difference, imposed by the API change.
- `deleteVm` refuses a suspended VM too (anything not `poweredOff`). That behavior is kept.
- The deletion loop is sequential and stops at the first failure: VMs already deleted stay deleted, and the workflow output is lost. That behavior is kept.

## Suggested improvements (not applied)

- Compute "days powered off" from vCenter events (`VmPoweredOffEvent`) or a tag, so that `minDaysOff` means something.
- Use Windmill's recorded approver (`approvers[0].approver`) instead of a free-text `approver` field; restrict approvers with `user_groups_required` / `self_approval_disabled` (Enterprise).
- Let `getPoweredOffVms` take `dry_run` returning sample VMs, so the whole flow can be walked without a vCenter.

## Verification commands run (workspace `internal_test`)

| Command | Result |
| --- | --- |
| `wmill generate-metadata f/vro` | pass, all metadata up to date |
| `wmill script preview f/vro/com_corp_vm/delete_vm.ts` (inline fake `vsphere`, `vm: vm-1234`, `dry_run: true`) | pass, returned `"vm-1234"` |
| `wmill script preview f/vro/com_corp_vm/get_powered_off_vms.ts` (inline fake `vsphere`) | fail as expected: `vCenter login failed: 502`, no vCenter at the fake host |
| `wmill flow preview ...clean_up_powered_off_vms__flow` (inline fake `vsphere`, `dry_run: true`) | fail as expected at `get_powered_off_vms`: login 502 |
| same, `vsphere` omitted | fail: the schema default `$res:f/vro/vsphere` is not applied by `flow preview`, so `vsphere` is null (`TypeError`) |
| same, `"vsphere": "$res:f/vro/vsphere"` | fail as expected: `Resource f/vro/vsphere not found` |
| `--step delete_approved_vms`, approved, `dry_run: true` | pass, `["vm-101","vm-102"]` |
| `--step delete_approved_vms`, rejected | pass, `[]` |
| `--step workflow_outputs` | pass |
| `--step approve_deletion` | pass, returned the resume / cancel / approval page URLs (a step preview does not suspend) |
| temporary mocked copy of the flow, step 1 returning `[]` | pass, `{"deleted": null}`; the copy was deleted |
