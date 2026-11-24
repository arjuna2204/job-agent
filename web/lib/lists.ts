/** "analyst, business development\ncredit" -> ["analyst","business development","credit"] */
export function parseList(v: FormDataEntryValue | null): string[] {
  return String(v || "")
    .split(/[\n,]/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
    .filter((s, i, a) => a.indexOf(s) === i)
    .slice(0, 100);
}
export const joinList = (a?: string[] | null) => (a || []).join(", ");
