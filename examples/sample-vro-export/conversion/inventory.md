# vRO migration inventory

1 workflows, 2 actions, 1 configuration elements.

No run history given (`--runs`), so no workflow is marked retire. Add it to find the ones unused for 365 days.

## Summary

| Verdict | Workflows | Actions | Becomes |
|---|---|---|---|
| retire | 0 | 0 | Do not migrate |
| merge | 0 | 0 | One flow with an input for what differs |
| wrapper | 0 | 0 | One Windmill script, or call the tool directly |
| rebuild | 1 | 2 | Script on the vSphere API / SDK (OpenTofu, pyvmomi, govmomi, PowerCLI, REST) |
| convert | 0 | 0 | TypeScript, Python or PowerShell script; flow for multi-step workflows |

Workflows with logic of their own to migrate: 1 of 1.

## Plugin dependencies

Each plugin is an integration to replace once and share across scripts.

| Plugin type / object | Used by |
|---|---|
| VC:VirtualMachine | 3 |
| VcPlugin | 1 |

## Workflows

| Verdict | Name | Category | Why |
|---|---|---|---|
| rebuild | Clean up powered-off VMs | Corp/VM | VC:VirtualMachine |

## Actions

| Verdict | Name | Category | Why |
|---|---|---|---|
| rebuild | deleteVm | com.corp.vm | VC:VirtualMachine |
| rebuild | getPoweredOffVms | com.corp.vm | VC:VirtualMachine, VcPlugin |

## Configuration elements

Each becomes a Windmill resource; SecureString attributes become secret fields or variables.

| Name | Category | Attributes | SecureStrings |
|---|---|---|---|
| vcenter_cleanup | Corp | 4 | 1 |

## Limits

- Action references are found statically (`System.getModule(...)` calls and action elements). Actions called dynamically show up as unreferenced.
- Merge candidates match on step structure and scripts with literals removed. Review each group before merging.
- Wrapper and convert are sized from script lines, not from what the scripts call.
