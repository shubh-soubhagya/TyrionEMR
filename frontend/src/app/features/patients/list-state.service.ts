import { Injectable, signal } from '@angular/core';

export type SortKey = 'name' | 'mrn' | 'age' | 'dx' | 'egfr' | 'visit';

/** Patient list filters, kept across navigation like the prototype's `ui.list` (html:531). */
@Injectable({ providedIn: 'root' })
export class ListStateService {
  readonly q = signal('');
  readonly sex = signal('');
  readonly stage = signal('');
  readonly attention = signal(false);
  readonly sort = signal<SortKey>('name');
  readonly dir = signal<1 | -1>(1);
  readonly page = signal(1);

  reset(): void {
    this.q.set('');
    this.sex.set('');
    this.stage.set('');
    this.attention.set(false);
    this.page.set(1);
  }
}
