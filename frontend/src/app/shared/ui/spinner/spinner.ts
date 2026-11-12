import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Small ring spinner. The HTML has no standalone spinner; this reuses its AI-step spinner look
 * (2px ring with a transparent top, `spin .8s linear infinite`). Decorative: pair with text.
 */
@Component({
  selector: 'emr-spinner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: ``,
  host: { 'aria-hidden': 'true', '[style.width.px]': 'size()', '[style.height.px]': 'size()' },
  styles: `
    :host {
      display: inline-block;
      flex: none;
      border-radius: 50%;
      border: 2px solid currentColor;
      border-top-color: transparent;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class EmrSpinner {
  readonly size = input(14);
}
