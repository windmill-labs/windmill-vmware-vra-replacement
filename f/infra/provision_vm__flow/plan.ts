// Turn a catalog request into a concrete VM spec and decide whether it needs approval.
// This is the logic a vRA blueprint and its approval policy used to hold.

const SIZES = {
  small: { cpus: 2, memory_mb: 4096, disk_gb: 40 },
  medium: { cpus: 4, memory_mb: 8192, disk_gb: 80 },
  large: { cpus: 8, memory_mb: 16384, disk_gb: 160 },
} as const;

// vSphere template name and default SSH user for each OS offered in the catalog.
const IMAGES = {
  "ubuntu-24.04": { template: "tpl-ubuntu-2404", ssh_user: "ubuntu" },
  "rhel-9": { template: "tpl-rhel-9", ssh_user: "cloud-user" },
} as const;

export async function main(
  vm_name: string,
  size: keyof typeof SIZES,
  os: keyof typeof IMAGES,
  environment: "dev" | "staging" | "prod",
) {
  if (!/^[a-z][a-z0-9-]{2,30}$/.test(vm_name)) {
    throw new Error(
      `Invalid VM name "${vm_name}": 3-31 chars, lowercase letters, digits and dashes, starting with a letter`,
    );
  }
  const spec = SIZES[size];
  const image = IMAGES[os];
  if (!spec) throw new Error(`Unknown size ${size}`);
  if (!image) throw new Error(`Unknown OS ${os}`);

  const reasons: string[] = [];
  if (environment === "prod") reasons.push("production environment");
  if (size === "large") reasons.push("large size");

  return {
    vm_name,
    environment,
    ...spec,
    ...image,
    needs_approval: reasons.length > 0,
    approval_reason: reasons.join(", "),
  };
}
