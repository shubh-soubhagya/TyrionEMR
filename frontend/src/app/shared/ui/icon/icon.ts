import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ICONS, IconName } from './icons';

/**
 * Decorative inline SVG icon (html `ic()` helper). Paths are our own constants, never user input,
 * so bypassing sanitisation is safe here. Always aria-hidden: pair it with visible text or an
 * aria-label on the parent control.
 */
@Component({
  selector: 'emr-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<svg
    class="ic"
    [attr.width]="size()"
    [attr.height]="size()"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    [innerHTML]="paths()"
  ></svg>`,
  styles: `
    :host {
      display: inline-flex;
      flex: none;
      vertical-align: middle;
    }
  `,
})
export class EmrIcon {
  private readonly sanitizer = inject(DomSanitizer);

  readonly name = input.required<IconName>();
  readonly size = input(18);

  protected readonly paths = computed<SafeHtml>(() =>
    this.sanitizer.bypassSecurityTrustHtml(ICONS[this.name()]),
  );
}
