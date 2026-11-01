export async function main(plan: any, provision: any, configure: any, dry_run: boolean) {
  return {
    vm_name: plan.vm_name,
    environment: plan.environment,
    ip_address: provision?.ip_address,
    moid: provision?.moid,
    size: { cpus: plan.cpus, memory_mb: plan.memory_mb, disk_gb: plan.disk_gb },
    configured: configure?.configured ?? false,
    dry_run,
  };
}
