# Windmill infrastructure automation examples

Infrastructure automation in [Windmill](https://www.windmill.dev): a VMware vRA catalog item and its vRO workflow rebuilt as a Windmill flow, plus the Day 2 jobs that usually sit next to it.

Companion repository to:

- [Infrastructure automation with Windmill](https://www.windmill.dev/use-cases/infra-automation)
- [Open source VMware vRA / vRO replacement](https://www.windmill.dev/use-cases/vmware-vra-replacement)

Everything here is plain files (TypeScript, Python, Ansible YAML, flow YAML) that the [Windmill CLI](https://www.windmill.dev/docs/advanced/cli) syncs to a workspace.
It runs on the open source Community Edition; the [Enterprise Edition](https://www.windmill.dev/pricing) options that make it stronger are listed at the end.

## What is in `f/infra`

| Path | Kind | What it does |
| --- | --- | --- |
| `provision_vm__flow` | Flow | The vRA catalog item: plan the spec, approval for prod or large requests, OpenTofu clone on vSphere, Ansible baseline, close the ServiceNow request. A failure handler destroys a half-built VM and notes the error on the ticket. A preprocessor maps a ServiceNow webhook payload to the inputs. |
| `decommission_vm__flow` | Flow | Approval, `tofu destroy` on the same state, ServiceNow note. |
| `rolling_patch__flow` | Flow | OS patching with a canary host, then fixed-size batches, one at a time. The first failed batch stops the run. |
| `tofu_vm.py` | Script | Creates or destroys one VM with OpenTofu or Terraform. State in Postgres (`pg` backend), one workspace per VM. |
| `configure_baseline.playbook.yml` | Ansible | Baseline for a new VM: hostname, chrony, unattended upgrades, environment tag. Builds its inventory at run time with `add_host`. |
| `patch_hosts.playbook.yml` | Ansible | Patches one batch, reboots when the OS asks for it. |
| `servicenow_update.ts` | Script | Work note and state change on any ServiceNow table, basic auth or OAuth. |
| `snapshot_sweeper.py` | Script + schedule | Deletes vSphere snapshots older than N days (pyvmomi). Dry run by default. |
| `cert_expiry_check.ts` | Script + schedule | Fails when a TLS certificate expires within N days, so the schedule error handler alerts. |
| `*.schedule.yaml` | Schedules | Nightly snapshot sweep, daily certificate check, weekly rolling patch. All ship disabled. |

```
provision_vm
  preprocessor   ServiceNow payload -> inputs (trigger runs only)
  plan           size + OS -> CPU, RAM, disk, template, needs_approval
  approval       suspend until approved (skipped for dev/small)
  provision      f/infra/tofu_vm  action=apply
  configure      f/infra/configure_baseline (Ansible)
  close_ticket   f/infra/servicenow_update
  summary
  failure        destroy the VM if it exists, note the ticket
```

## How vRO objects map

| vRO / vRA | Here |
| --- | --- |
| Catalog item + custom form | The flow's generated input form (enums, patterns, defaults in `schema`) |
| Approval policy | `approval` step with `suspend`, `skip_if` decides when it applies |
| Workflow | Flow (`flow.yaml`) |
| Action (JavaScript) | Script (`.ts`, `.py`, `.ps1`, `.sh`...) |
| Configuration element | Resource or variable (`f/infra/vsphere`, `f/infra/ssh_private_key`) |
| SecureString | Secret variable, or a secret field in a resource |
| Policy / scheduled workflow | Schedule (`*.schedule.yaml`) |
| Event subscription | Webhook, HTTP route, Kafka, NATS, SQS, MQTT, Postgres CDC or email trigger with a preprocessor |
| Package export | Git, synced with `wmill sync` |

## Setup

### 1. Workers

- Ansible scripts need the `windmill-full` (or `windmill-ee-full`) worker image.
- `tofu_vm.py` needs `tofu` or `terraform` on the worker's PATH. Either bake it into a custom image, or add it in a worker group init script (Enterprise):

  ```bash
  curl -fsSL https://get.opentofu.org/install-opentofu.sh -o /tmp/install-opentofu.sh
  sh /tmp/install-opentofu.sh --install-method standalone --skip-verify
  ```

  To keep it on a dedicated group, give that group a tag such as `infra` and set `tag: infra` in `f/infra/tofu_vm.script.yaml`.
- The workers that run `tofu_vm`, the playbooks and `snapshot_sweeper` must reach vCenter and the VMs' network. If they live in another network segment, run an [agent worker](https://www.windmill.dev/docs/core_concepts/agent_workers) there (Enterprise): it only opens outbound HTTP to Windmill.

### 2. Push to a workspace

```bash
npm install -g windmill-cli
wmill workspace add infra <workspace_id> https://your-windmill-host/
wmill resource-type push c_vsphere.resource-type.json   # or sync it with the rest
wmill sync push
```

### 3. Resources and variables

Create these in the workspace (UI or `wmill sync`):

| Path | Type | Notes |
| --- | --- | --- |
| `f/infra/vsphere` | `c_vsphere` | vCenter, service account, datacenter, cluster, datastore, port group, folder, DNS domain |
| `f/infra/tf_state` | `postgresql` | Any Postgres the workers reach. OpenTofu creates the `windmill_vsphere_vms` schema |
| `f/infra/servicenow` | `servicenow` | Basic auth or the ServiceNow OAuth connection |
| `f/infra/ssh_private_key` | secret variable | Matches the key in the templates' `authorized_keys`. Keep the trailing newline |

The templates are named in `provision_vm__flow/plan.ts` (`tpl-ubuntu-2404`, `tpl-rhel-9`). Rename them to match vCenter.

## Try it without vSphere

Every flow has a `dry_run` input that walks all steps without touching vSphere, the VMs or ServiceNow:

```bash
wmill flow preview f/infra/rolling_patch__flow \
  -d '{"hosts":["web-01","web-02","web-03","web-04","web-05"],"batch_size":2,"require_approval":false,"dry_run":true}'

wmill flow preview f/infra/provision_vm__flow --step plan \
  -d '{"vm_name":"app-web-01","size":"large","os":"rhel-9","environment":"prod"}'

wmill script preview f/infra/cert_expiry_check.ts -d '{"endpoints":["www.windmill.dev:443"],"warn_days":21}'
```

`provision_vm` and `decommission_vm` in dry run still resolve `f/infra/vsphere` and `f/infra/tf_state`, so create those resources first (placeholder values are fine in dry run).

## Start provisioning from ServiceNow

1. On `f/infra/provision_vm`, add a [webhook](https://www.windmill.dev/docs/core_concepts/webhooks) or an [HTTP route](https://www.windmill.dev/docs/triggers/http_routing) trigger, and create a token scoped to that flow.
2. In ServiceNow, have a business rule or a Flow Designer REST step on the catalog item POST:

   ```json
   { "number": "RITM0010001",
     "variables": { "vm_name": "app-web-01", "size": "medium", "os": "ubuntu-24.04", "environment": "dev" } }
   ```

3. The preprocessor turns that body into flow inputs. The flow closes the RITM when the VM is configured, or writes the error on it when a step fails.

## Enterprise options

These examples run on the Community Edition.
On the [Enterprise Edition](https://www.windmill.dev/pricing), the same flows can also use:

- Approval forms and approver restrictions (required group, no self-approval) on the `approval` steps.
- Worker group init scripts and tags managed from the UI, and agent workers in isolated networks.
- Vault, Azure Key Vault or AWS Secrets Manager as the secret backend for the vCenter and ServiceNow credentials.
- Kafka, NATS, SQS and GCP Pub/Sub triggers for event-driven Day 2 jobs.
- Audit logs kept for a year, and protection rulesets on the workspace that holds these flows.
- Native Windows workers for PowerShell and PowerCLI against vCenter.
