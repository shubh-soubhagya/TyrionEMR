import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { EmrButton } from '../button/button';

/** Pager bar (html `.pager`): summary text on the left, Previous / Page x of y / Next on the right. */
@Component({
  selector: 'emr-pagination',
  imports: [EmrButton],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span>{{ summary() }}</span>
    <div class="row">
      <button
        emr-button
        size="sm"
        type="button"
        icon="left"
        [disabled]="page() <= 1"
        (click)="pageChange.emit(page() - 1)"
      >
        Previous
      </button>
      <span>Page {{ page() }} of {{ pages() }}</span>
      <button
        emr-button
        size="sm"
        type="button"
        iconEnd="right"
        [disabled]="page() >= pages()"
        (click)="pageChange.emit(page() + 1)"
      >
        Next
      </button>
    </div>
  `,
  styles: `
    :host {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--space-10) var(--space-14);
      border-top: 1px solid var(--color-border-default);
      font-size: var(--fs-13);
      color: var(--color-text-muted);
    }
    .row {
      display: flex;
      gap: var(--space-10);
      align-items: center;
    }
  `,
})
export class EmrPagination {
  readonly page = input.required<number>();
  readonly total = input.required<number>();
  readonly pageSize = input.required<number>();
  /** Noun for the summary, e.g. "patients" or "results". */
  readonly noun = input('results');
  readonly pageChange = output<number>();

  protected readonly pages = computed(() => Math.max(1, Math.ceil(this.total() / this.pageSize())));
  protected readonly summary = computed(() => {
    const total = this.total();
    if (!total) return `0 ${this.noun()}`;
    const first = (this.page() - 1) * this.pageSize() + 1;
    const last = Math.min(this.page() * this.pageSize(), total);
    return `Showing ${first}–${last} of ${total} ${this.noun()}`;
  });
}
