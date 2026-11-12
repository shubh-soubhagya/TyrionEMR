import {
  ChangeDetectionStrategy,
  Component,
  Directive,
  TemplateRef,
  computed,
  contentChildren,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { EmrEmptyState } from '../empty-state/empty-state';
import { EmrErrorState } from '../error-state/error-state';
import { EmrSkeleton } from '../skeleton/skeleton';

export interface ColumnDef {
  /** Identifies the column; also the property read when there is no custom cell. */
  readonly key: string;
  readonly header: string;
  readonly align?: 'start' | 'end';
  readonly sortable?: boolean;
  readonly nowrap?: boolean;
}

export interface SortState {
  readonly key: string;
  readonly dir: 'asc' | 'desc';
}

export interface EmrCellContext<T> {
  $implicit: T;
  index: number;
}

/**
 * Custom cell template for one column:
 *   <ng-template emrCell="name" [emrCellOf]="rows" let-row let-i="index">{{ row.name }}</ng-template>
 * `emrCellOf` is only there so TypeScript can infer the row type for `let-row`.
 */
@Directive({ selector: 'ng-template[emrCell]' })
export class EmrCell<T = unknown> {
  readonly key = input.required<string>({ alias: 'emrCell' });
  readonly emrCellOf = input<readonly T[]>();
  readonly template = inject<TemplateRef<EmrCellContext<T>>>(TemplateRef);

  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- parameters only declare the guard type
  static ngTemplateContextGuard<T>(_dir: EmrCell<T>, _ctx: unknown): _ctx is EmrCellContext<T> {
    return true;
  }
}

export type TableState = 'loading' | 'ready' | 'error';

/**
 * Generic table (html `table`, `th`, `td`, `tr.click`). Handles its own loading (skeleton rows),
 * empty and error states. Rows can be clickable and are keyboard-activatable (Enter / Space),
 * which the HTML prototype lacks.
 */
@Component({
  selector: 'emr-data-table',
  imports: [NgTemplateOutlet, EmrSkeleton, EmrEmptyState, EmrErrorState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './data-table.html',
  styleUrl: './data-table.scss',
})
export class EmrDataTable<T> {
  readonly columns = input.required<readonly ColumnDef[]>();
  readonly rows = input.required<readonly T[]>();
  readonly state = input<TableState>('ready');
  /** Stable identity for `@for` tracking; defaults to the row index. */
  readonly rowKey = input<(row: T, index: number) => string | number>((_row, index) => index);
  readonly rowClickable = input(false);
  /** Accessible name for the table. */
  readonly label = input.required<string>();

  readonly emptyTitle = input('Nothing to show');
  readonly emptyText = input('');
  readonly errorMessage = input('The data could not be loaded.');
  readonly skeletonRows = input(4);

  readonly sortKey = model<string>();
  readonly sortDir = model<'asc' | 'desc'>('asc');

  readonly rowClick = output<T>();
  readonly sortChange = output<SortState>();
  readonly retry = output<void>();

  private readonly cells = contentChildren(EmrCell);
  protected readonly templates = computed(
    () => new Map(this.cells().map((cell) => [cell.key(), cell.template])),
  );
  protected readonly skeletonList = computed(() =>
    Array.from({ length: this.skeletonRows() }, (_, i) => i),
  );

  protected trackRow(index: number, row: T): string | number {
    return this.rowKey()(row, index);
  }

  /** Text of a plain cell; null when the value is missing (0 is a real value). */
  protected cellText(row: T, key: string): string | null {
    const value = (row as Record<string, unknown>)[key];
    return typeof value === 'string' && value.trim() !== ''
      ? value
      : typeof value === 'number'
        ? String(value)
        : null;
  }

  protected ariaSort(col: ColumnDef): 'ascending' | 'descending' | 'none' | null {
    if (!col.sortable) return null;
    if (this.sortKey() !== col.key) return 'none';
    return this.sortDir() === 'asc' ? 'ascending' : 'descending';
  }

  protected toggleSort(col: ColumnDef): void {
    const dir = this.sortKey() === col.key && this.sortDir() === 'asc' ? 'desc' : 'asc';
    this.sortKey.set(col.key);
    this.sortDir.set(dir);
    this.sortChange.emit({ key: col.key, dir });
  }

  protected activate(row: T, event?: Event): void {
    if (!this.rowClickable()) return;
    event?.preventDefault();
    this.rowClick.emit(row);
  }
}
