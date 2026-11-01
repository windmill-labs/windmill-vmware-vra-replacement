export async function main(target_hosts: string[]) {
  console.log(`[dry run] would patch: ${target_hosts.join(", ")}`);
  return { patched: target_hosts, count: target_hosts.length, dry_run: true };
}
