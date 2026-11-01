// The vRO workflow's output parameter `deleted` (Array/string).
// It stays unset (null) when the decision "Anything to delete?" takes the false path.
export async function main(deleted: string[] | null) {
  return { deleted };
}
