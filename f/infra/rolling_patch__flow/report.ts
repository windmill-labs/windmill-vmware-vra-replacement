export async function main(batches: string[][], results: any[], dry_run: boolean) {
  return {
    batches: batches.length,
    hosts_patched: batches.flat().length,
    per_batch: results,
    dry_run,
  };
}
