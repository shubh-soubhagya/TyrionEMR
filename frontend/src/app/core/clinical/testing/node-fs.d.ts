// The shared-vector spec reads one file with node:fs. A two-function declaration here avoids adding @types/node (and
// its whole Node API surface) to a browser project for a single test.
declare module 'node:fs' {
  export function existsSync(path: string): boolean;
  export function readFileSync(path: string, encoding: 'utf-8'): string;
}
