import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Shimmer bars (html `.skel`). `widths` are CSS widths, one bar each, e.g. ['30%', '90%']. */
@Component({
  selector: 'emr-skeleton',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (width of widths(); track $index) {
      <div class="skel" [style.width]="width"></div>
    }
  `,
  host: { 'aria-hidden': 'true' },
  styles: `
    :host {
      display: block;
    }
    .skel {
      height: 14px;
      border-radius: var(--radius-sm);
      margin-bottom: var(--space-10);
      background: linear-gradient(
        90deg,
        var(--color-skeleton-1),
        var(--color-skeleton-2),
        var(--color-skeleton-1)
      );
      background-size: 200% 100%;
      animation: sk 1.1s infinite;
    }
    .skel:last-child {
      margin-bottom: 0;
    }
    @keyframes sk {
      to {
        background-position: -200% 0;
      }
    }
  `,
})
export class EmrSkeleton {
  /** Default mirrors the HTML's 4-line placeholder (html:652). */
  readonly widths = input<readonly string[]>(['30%', '90%', '80%', '60%']);
}
