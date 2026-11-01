---
name: vro-to-windmill
description: Convert VMware vRealize Orchestrator (vRO / Aria Automation / VCF Automation) workflows, actions and configuration elements into Windmill scripts, flows and resources. Use when asked to migrate, port or convert vRO content, a .package export, or a Build Tools for VMware Aria project to Windmill.
---

# Convert vRO content to Windmill

You are converting a vRealize Orchestrator estate to Windmill, one element at a time, keeping behavior identical.
The person reviews every conversion, so favor faithful and explicit over clever.

This skill orchestrates the conversion. For the syntax of each target, also read the Windmill skills in this repository: `write-script-bun`, `write-script-python3`, `write-script-powershell`, `write-flow`, `resources` and `cli-commands`.

## 0. Inventory and extract

Never read raw `.package` files: their XML is UTF-16 inside a zip. Run the inventory script first, with extraction:

```bash
python3 tools/vro_inventory.py <exports...> --out vro/inventory.md --json vro/inventory.json --extract vro/src
```

Add `--runs runs.csv` if the person has last-run dates. Then read `vro/inventory.md` and tell the person, before converting anything:

- the counts per verdict (retire, merge, wrapper, rebuild, convert)
- the plugin dependency table: each row is a shared helper you will write once
- the merge groups, and ask whether to merge each group into one flow with an input

`vro/src` now holds:

- `actions/<category>/<name>.js|py|ps1`: the action source, with a header listing its params, return type, runtime and verdict
- `workflows/<category>/<name>.json`: inputs, outputs, attributes, and every step (`items`) with its type, `next` (`alt_next` for the false branch of a decision), `on_error`, bindings and script
- `configurations/<category>/<name>.json`: attribute names and types

## 1. Order of work

1. Skip `retire`. List what you skipped in the report; never delete anything in vRO.
2. Shared helpers first, one per plugin in the dependency table (for example `f/vro/lib/vsphere.ts` for `VC:*` and `VcPlugin`). Actions import them.
3. Configuration elements, as resources (step 3).
4. Actions, leaves first: an action that other actions call (`System.getModule(...)`) before its callers.
5. Workflows, bottom-up: a workflow that others link to (`link` items) before the workflows that link to it.

Convert one element, verify it (step 6), then move to the next. Don't batch twenty conversions and verify at the end.

## 2. Actions become scripts

Path: `f/vro/<category>/<name>` with dots in the category turned into underscores (`com.corp.vm/getPoweredOffVms` → `f/vro/com_corp_vm/get_powered_off_vms.ts`).
Language: JavaScript actions become Bun TypeScript; `python` runtime actions stay Python; `powercli` / PowerShell actions stay PowerShell.
Keep the original source as a comment block at the top of the new script, with the vRO path and id.

Parameters become `main` arguments, in the same order and with the same names:

| vRO type | Windmill argument |
| --- | --- |
| `string`, `number`, `boolean` | `string`, `number`, `boolean` |
| `Date` | `string` (ISO 8601); parse inside |
| `Properties` | `Record<string, unknown>` |
| `Array/X` | `X[]` |
| `Any` | `unknown` |
| `CompositeType(a:string,b:number):Name` | an object type `{ a: string; b: number }` |
| `SecureString` | a secret: a field of a resource, or a secret variable passed in. Never a plain string default |
| Plugin object (`VC:VirtualMachine`, `REST:RESTHost`, `AD:User`...) | a resource for the connection (`vmware_vsphere` for vCenter) plus the object's id as a string (for vSphere, the managed object id such as `vm-1234`) |

Return values: return the same shape. Plugin objects in returns become plain JSON with at least the id and name.

Translations inside the body:

| vRO JavaScript | Windmill |
| --- | --- |
| `System.log / warn / error / debug` | `console.log / warn / error / debug` |
| `System.getModule("a.b").fn(x)` | `import { main as fn } from "/f/vro/a_b/fn"` and `await fn(x)` |
| `System.sleep(ms)` | `await new Promise((r) => setTimeout(r, ms))` |
| `throw "message"` | `throw new Error("message")` |
| `new Properties()`, `.get / .put` | a plain object |
| `RESTHost.createRequest(...).execute()` | `fetch`, with the host and credentials from a resource |
| `VcPlugin.*`, `Server.findAllForType("VC:...")` | the shared vSphere helper, on the vSphere Automation REST API (`/api/...`, vCenter 7.0 U2+), or pyvmomi / PowerCLI where REST has no equivalent |
| Configuration element lookups | the resource, passed as an argument (preferred) or read with `wmill.getResource("f/vro/...")` |
| `var`, `for (var i in array)` | `const` / `let`, `for (const x of array)` |

Keep the logic the same, including its quirks. If you see a bug, keep the behavior, mark it `// NOTE(vro): ...` and list it in the report.

## 3. Configuration elements become resources

One resource per configuration element, at `f/vro/<category>/<name>`.
Connection-shaped ones (host, user, password) use an existing Hub resource type when one fits (`vmware_vsphere`, `servicenow`, `netbox`, `postgresql`, `smtp`...).
Otherwise write a custom resource type named `c_<name>` with one field per attribute, and mark `SecureString` attributes `"password": true`.
Never copy secret values: create the resource with empty secrets, and tell the person which ones to fill.

## 4. Workflows become flows

Create the flow with `wmill flow new f/vro/<category>/<name> --summary "..."`, then write `flow.yaml` following the `write-flow` skill.
Walk the items from the workflow's start item along `next`:

| vRO item `type` | Flow module |
| --- | --- |
| `task` with `action` set | `type: script` with `path:` the converted action |
| `task` (scriptable task) | `type: rawscript`, Bun, the script body as a `main` whose arguments are the item's `in` bindings |
| `link` | `type: flow` with `path:` the converted workflow (look up `linked_workflow_id` in `vro/inventory.json`) |
| `custom-condition`, `condition`, decision items | `branchone`: `next` is the path when the decision returns true, `alt_next` when false. Put the decision in the branch `expr`, or in a small rawscript before it when it needs more than one expression |
| `foreach` | `forloopflow` over the bound array |
| `input` (user interaction) | an approval step: module-level `suspend` with a `resume_form` holding the interaction's fields |
| `waiting-timer` | module-level `sleep` |
| `end` | nothing (end of the flow, or of the branch) |
| `on_error` set | `retry` on the step if the error path retries, `failure_module` if it cleans up, `continue_on_error` if it logs and goes on |

Data flow: workflow inputs become the flow `schema`; an `in` binding from an input becomes `flow_input.<name>`, from a previous item's `out` binding becomes `results.<step_id>.<field>`.
Workflow attributes with a constant value become static inputs or a resource; attributes that hold plugin objects become resource inputs.

## 5. Safety rules

- Every script that changes infrastructure takes `dry_run: boolean = false` and, when true, logs what it would do and returns a plausible result without calling the target. Flows pass `dry_run` down.
- Don't invent API endpoints, fields or SDK methods. If you aren't sure an endpoint exists for the vCenter version in use, write `// TODO(vro): verify` and list it in the report.
- No credentials in code, defaults or comments.
- Don't change behavior while converting: no added retries, renamed outputs or "improved" logic. Suggest improvements in the report instead.

## 6. Verify each conversion

```bash
wmill generate-metadata f/vro/<category>      # schema and lockfile
wmill script preview f/vro/<category>/<name>.ts -d '{"dry_run": true, ...}'
wmill flow preview f/vro/<category>/<name>__flow -d '{"dry_run": true, ...}'
```

Pick arguments from the vRO params. A preview that fails because a resource doesn't exist yet is fine; say so. Fix anything else before moving on.

## 7. Report

Keep `vro/conversion-report.md` up to date as you go, one row per element:

| vRO element | Verdict | Windmill path | Status | Notes |
| --- | --- | --- | --- | --- |
| `com.corp.vm/getPoweredOffVms` | rebuild | `f/vro/com_corp_vm/get_powered_off_vms.ts` | dry run passed | `VcPlugin` → vSphere REST |

Status is one of: converted, dry run passed, needs resource, needs review, skipped (retire), merged into `<path>`.
End with the list of resources and secrets the person must create, every `TODO(vro)`, and every `NOTE(vro)`.
