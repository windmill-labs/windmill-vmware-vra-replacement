---
name: vro-to-windmill
description: Convert VMware vRealize Orchestrator (vRO / Aria Automation / VCF Automation) workflows, actions and configuration elements into Windmill scripts, flows and resources. Use when asked to migrate, port or convert vRO content, a .package export, or a Build Tools for VMware Aria project to Windmill.
---

# Convert vRO content to Windmill

You are converting a vRealize Orchestrator estate to Windmill, one element at a time, keeping behavior identical.
The person reviews every conversion, so favor faithful and explicit over clever.

This skill orchestrates the conversion. For the syntax of each target, also read the Windmill skills in this repository: `write-script-bun`, `write-script-python3`, `write-script-powershell`, `write-flow`, `resources` and `cli-commands`.

When the person has asked you to convert vRO content, that request covers the commands this skill runs: `wmill flow new` with the paths below, `wmill generate-metadata` on `f/vro/`, and previews with `dry_run`. Don't stop to confirm each one, even where the generic Windmill guidance says to ask first. Deploying (`wmill sync push`, `git push`) still needs an explicit request.

## 0. Inventory and extract

Never read raw `.package` files: their XML is UTF-16 inside a zip. Run the inventory script first, with extraction:

```bash
python3 tools/vro_inventory.py <exports...> --out vro/inventory.md --json vro/inventory.json --extract vro/src
```

Add `--runs runs.csv` if the person has last-run dates. Then read `vro/inventory.md` and tell the person, before converting anything:

- the counts per verdict (retire, merge, wrapper, rebuild, convert)
- the plugin dependency table: each row is a shared helper you will write once
- the "Referenced but not in this export" list (VMware library actions and other packages, see step 2)
- the merge groups. Ask whether to merge each group into one flow with an input; if you can't ask, convert them separately and list them in the report

`vro/src` now holds, with category dots and slashes turned into directories (`com.corp.vm` → `com/corp/vm`):

- `actions/<category dirs>/<name>.js|py|ps1`: the action source, with a header listing its description, params, return type, runtime and verdict
- `workflows/<category dirs>/<name>.json`: description, `start` (the first item), inputs, outputs, attributes, and every step (`items`) with its type, `next` (`alt_next` for the false branch of a decision), `on_error`, bindings and script
- `configurations/<category dirs>/<name>.json`: attribute names and types

## 1. Order of work and naming

1. Skip `retire`. List what you skipped in the report; never delete anything in vRO.
2. Connections first: one resource per target system (step 3).
3. Shared helpers, one per plugin in the dependency table (for example `f/vro/lib/vsphere.ts` for `VC:*` and `VcPlugin`). Actions import them.
4. Configuration elements, as resources (step 3).
5. Actions, leaves first: an action that other actions call (`System.getModule(...)`) before its callers.
6. Workflows, bottom-up: a workflow that others link to (`link` items) before the workflows that link to it.

Convert one element, verify it (step 6), then move to the next. Don't batch twenty conversions and verify at the end.

Paths: `f/vro/<category>/<name>`, where the category is lowercased with every `.`, `/`, space and hyphen turned into `_`, and the name is snake_cased the same way (camelCase splits on capitals).
`com.corp.vm/getPoweredOffVms` → `f/vro/com_corp_vm/get_powered_off_vms.ts`; workflow `Corp/VM` + `Clean up powered-off VMs` → `f/vro/corp_vm/clean_up_powered_off_vms__flow`.

## 2. Actions become scripts

Language: JavaScript actions become Bun TypeScript; `python` runtime actions stay Python; `powercli` / PowerShell actions stay PowerShell.
Keep the original source as a comment block at the top of the new script, with the vRO path, id and description.

Arguments, in this order: connection resources first, then the vRO params with the same names and order, then `dry_run` if the script takes one (step 5).

| vRO type | Windmill argument |
| --- | --- |
| `string`, `number`, `boolean` | `string`, `number`, `boolean` |
| `Date` | `string` (ISO 8601); parse inside |
| `Properties` | `Record<string, unknown>` |
| `Array/X` | `X[]` |
| `Any` | `unknown` |
| `CompositeType(a:string,b:number):Name` | an object type `{ a: string; b: number }` |
| `SecureString` | a secret: a field of a resource, or a secret variable passed in. Never a plain string default |
| Plugin object (`VC:VirtualMachine`, `REST:RESTHost`, `AD:User`...) | the connection resource (`vmware_vsphere` for vCenter) plus the object's id as a string (for vSphere, the managed object id such as `vm-1234`) |

Return values: return the same shape. Plugin objects in returns become plain JSON with at least the id and name.

Translations inside the body:

| vRO JavaScript | Windmill |
| --- | --- |
| `System.log / warn / error / debug` | `console.log / warn / error / debug` |
| `System.getModule("a.b").fn(x)` | `import { main as fn } from "/f/vro/a_b/fn"` and `await fn(x)` |
| `System.getModule("com.vmware.library...")...` | not in the export: replace with what it does. `vim3WaitTaskEnd` becomes waiting on the REST call or polling `/api/cis/tasks`; other library actions become a call in the shared helper |
| `System.sleep(ms)` | `await new Promise((r) => setTimeout(r, ms))` |
| `throw "message"` | `throw new Error("message")` |
| `new Properties()`, `.get / .put` | a plain object |
| `RESTHost.createRequest(...).execute()` | `fetch`, with the host and credentials from a resource |
| `VcPlugin.*`, `Server.findAllForType("VC:...")` | the shared vSphere helper (below) |
| Configuration element lookups | the resource, passed as an argument (preferred) or read with `wmill.getResource("f/vro/...")` |
| `var`, `for (var i in array)` | `const` / `let`, `for (const x of array)` |

The shared vSphere helper uses the vSphere Automation REST API (`/api/...`, vCenter 7.0 U2+) by default.
When an action reads a property REST doesn't expose (for example `runtime.bootTime`, snapshot trees, custom fields), keep the action in TypeScript if the person accepts the gap, with a `TODO(vro)` and a `NOTE(vro)` explaining it, or write that action in Python with pyvmomi, which reaches the full vSphere API. Don't mix languages inside one script.

A helper is a script with no `main`: Windmill treats it as shared code, imported by other scripts, and doesn't list it as runnable. Don't make it a `//native` script if it needs Node APIs (such as TLS options for `allow_unverified_ssl`).

Keep the logic the same, including its quirks. If you see a bug, keep the behavior, mark it `// NOTE(vro): ...` and list it in the report.

## 3. Connections and configuration elements become resources

Connections: one resource per target system, at `f/vro/<system>` (`f/vro/vsphere` for vCenter), using the Hub resource type when one exists (`vmware_vsphere`, `servicenow`, `netbox`, `postgresql`, `smtp`...).
Scripts and flows take it as an argument; flows declare it as an input with the resource path as default.

Configuration elements, one at a time:

- All attributes are a connection a Hub type covers: they are that connection resource. Don't create a second one.
- Some attributes are a connection, the rest are settings: the connection attributes go into the connection resource, the rest into a resource of a custom type `c_<name>` at `f/vro/<category>/<name>`. Never keep the same credentials in two resources.
- No connection: a `c_<name>` resource with one field per attribute.

Mark `SecureString` attributes `"password": true` in the custom type. Never copy secret values: create resources with empty secrets and tell the person which to fill.
Write custom resource types as `c_<name>.resource-type.yaml` at the repository root (or `.json` only if `wmill.yaml` sets `json: true`), with `description` and `schema` keys: that's the file name `wmill sync` picks up.

## 4. Workflows become flows

Create the flow with `wmill flow new f/vro/<category>/<name> --summary "..."`, then write `flow.yaml` following the `write-flow` skill.
Walk the items from `start` along `next`:

| vRO item `type` | Flow module |
| --- | --- |
| `task` with `action` set | `type: script` with `path:` the converted action |
| `task` (scriptable task) | `type: rawscript`, Bun. Its `main` takes the connection resources it needs, then the item's `in` bindings, then `dry_run` if it changes infrastructure |
| `link` | `type: flow` with `path:` the converted workflow (look up `linked_workflow_id` in `vro/inventory.json`) |
| `custom-condition`, `condition`, decision items | `branchone`: `next` is the path when the decision returns true, `alt_next` when false. Put the decision in the branch `expr`, or in a small rawscript before it when it needs more than one expression |
| `foreach` | `forloopflow` over the bound array |
| `input` (user interaction) | an approval step: module-level `suspend` with a `resume_form` holding the interaction's output fields. The next step reads them as `resume.<field>` |
| `waiting-timer` | module-level `sleep` |
| `end` | nothing (end of the flow, or of the branch) |
| `on_error` set | `retry` on the step if the error path retries, `failure_module` if it cleans up, `continue_on_error` if it logs and goes on |

Data flow: workflow inputs become the flow `schema`; an `in` binding from an input becomes `flow_input.<name>`, from a previous item's `out` binding becomes `results.<step_id>.<field>`.
Workflow attributes with a constant value become static inputs or a resource; attributes that hold plugin objects become the connection input plus ids.

Approvals: in Windmill, Cancel on an approval cancels the whole flow. If the vRO workflow continued after a rejection (a boolean like `approved` that a later step checks), keep that field in the resume form so the rejection path still runs, and say so in the report.

Outputs: end the flow with a step that returns an object holding the workflow's output parameters. Every branch must produce the same shape; on a path where vRO left an output unset, return `null` for it.

## 5. Safety rules

- Every script that changes infrastructure takes `dry_run: boolean = false` and, when true, logs what it would do and returns a plausible result without calling the target. Flows take `dry_run` and pass it down.
- Read-only scripts don't take `dry_run`: they call the target even in a flow's dry run. To test a flow without a target, preview the steps after them on their own (`--step`) with sample inputs, or set `mock` on the read step temporarily and remove it afterwards.
- Don't invent API endpoints, fields or SDK methods. If you aren't sure an endpoint exists for the vCenter version in use, write `// TODO(vro): verify` and list it in the report.
- No credentials in code, defaults or comments.
- Don't change behavior while converting: no added retries, renamed outputs or "improved" logic. Suggest improvements in the report instead.

## 6. Verify each conversion

```bash
wmill generate-metadata f/vro/<category>      # schema and lockfile
wmill script preview f/vro/<category>/<name>.ts -d '{"dry_run": true, ...}'
wmill flow preview f/vro/<category>/<name>__flow -d '{"dry_run": true, ...}'
wmill flow preview f/vro/<category>/<name>__flow --step <step_id> -d '{...}'
```

Pass every input explicitly: `flow preview` doesn't apply schema defaults, so an omitted input arrives as `null`.
For script previews, pass resources inline as objects with fake values rather than `$res:` paths.
These failures are expected without the real systems, and are not bugs in the conversion: a `$res:` resource that doesn't exist yet, a login or network error against a fake host, and a flow that stops at its first read step. Anything else, fix before moving on.

## 7. Report

Keep `vro/conversion-report.md` up to date as you go. Start it with the connection resources you created, then one row per element:

| vRO element | Verdict | Windmill path | Status | Notes |
| --- | --- | --- | --- | --- |
| `com.corp.vm/deleteVm` | rebuild | `f/vro/com_corp_vm/delete_vm.ts` | dry run passed | `destroy_Task` → `DELETE /api/vcenter/vm/{vm}` |

Status is one of: converted, dry run passed, steps previewed (each step passes on its own, the whole flow needs the target), needs resource, needs review, skipped (retire), merged into `<path>`.
End with the decisions you took without asking, the resources and secrets the person must create, every `TODO(vro)`, and every `NOTE(vro)`.
