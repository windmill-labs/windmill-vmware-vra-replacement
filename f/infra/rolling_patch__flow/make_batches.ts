// Split the fleet into batches. The canary batch (first host alone) goes first,
// so a bad package update hits one machine before it hits a whole batch.
export async function main(hosts: string[], batch_size: number, canary: boolean) {
  const clean = [...new Set(hosts.map((h) => h.trim()).filter(Boolean))];
  if (clean.length === 0) throw new Error("No hosts given");
  const size = Math.max(1, Math.floor(Number(batch_size) || 5));
  const batches: string[][] = [];
  let rest = clean;
  if (canary !== false && clean.length > 1) {
    batches.push([clean[0]]);
    rest = clean.slice(1);
  }
  for (let i = 0; i < rest.length; i += size) batches.push(rest.slice(i, i + size));
  return { total: clean.length, batches };
}
