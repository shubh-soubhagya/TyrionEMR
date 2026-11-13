// Formatting and tiny helpers from the HTML's script (html:306-326). en-GB date style, as in the prototype.
export const DAY = 86400000;
export const pad = (n: number): string => String(n).padStart(2, '0');
export const cap = (s: string): string => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

export const isoDate = (d: number | string | Date): string => {
  const x = new Date(d);
  return x.getFullYear() + '-' + pad(x.getMonth() + 1) + '-' + pad(x.getDate());
};

export const fmtDate = (d: number | string | Date | null | undefined): string =>
  d
    ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    : '-';

export const fmtDT = (d: number | string | Date | null | undefined): string =>
  d
    ? new Date(d).toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '-';

export const localInput = (d: Date = new Date()): string =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);

export const signed = (v: number, d = 1): string =>
  (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);

export function ageOf(dob: string | number | Date, at?: string | number | Date): number {
  const d = new Date(dob);
  const n = at ? new Date(at) : new Date();
  let a = n.getFullYear() - d.getFullYear();
  const m = n.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && n.getDate() < d.getDate())) a--;
  return a;
}
