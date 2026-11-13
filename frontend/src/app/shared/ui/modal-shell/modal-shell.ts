import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  inject,
  input,
  output,
} from '@angular/core';
import { EmrIcon } from '../icon/icon';

/**
 * The prototype's modal (html `openModal`, html:633): fixed backdrop, white dialog, header with title,
 * subtitle and close button. Escape and a click on the backdrop close it; the first field is focused.
 */
@Component({
  selector: 'emr-modal-shell',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="backdrop"
      tabindex="-1"
      (mousedown)="onBackdrop($event)"
      (keydown.escape)="closed.emit()"
    >
      <div
        class="modal"
        [class]="size()"
        role="dialog"
        aria-modal="true"
        [attr.aria-label]="title()"
      >
        <div class="modal-h">
          <div>
            <h2>{{ title() }}</h2>
            @if (sub()) {
              <p>{{ sub() }}</p>
            }
          </div>
          <button class="icon-btn" type="button" aria-label="Close" (click)="closed.emit()">
            <emr-icon name="x" />
          </button>
        </div>
        <div class="modal-b"><ng-content /></div>
      </div>
    </div>
  `,
})
export class EmrModalShell {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  readonly title = input.required<string>();
  readonly sub = input<string>();
  readonly size = input<'md' | 'lg' | 'sm'>('md');
  readonly closed = output<void>();

  constructor() {
    afterNextRender(() => {
      const first = this.host.nativeElement.querySelector<HTMLElement>(
        '.modal-b input:not([type=hidden]):not([readonly]), .modal-b select, .modal-b textarea',
      );
      first?.focus();
    });
  }

  protected onBackdrop(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('backdrop')) this.closed.emit();
  }
}
