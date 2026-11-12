import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  effect,
  input,
  model,
  output,
  viewChild,
} from '@angular/core';
import { EmrIcon } from '../icon/icon';

let nextModalId = 0;

/**
 * Dialog on the native <dialog> element opened with showModal(): the browser traps focus inside,
 * makes the rest of the page inert, closes on Escape and puts focus back on the element that
 * opened it. `open` is two-way. The HTML's backdrop click also closes it (kept).
 */
@Component({
  selector: 'emr-modal',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './modal.html',
  styleUrl: './modal.scss',
})
export class EmrModal {
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  readonly open = model(false);
  readonly title = input.required<string>();
  readonly subtitle = input<string>();
  readonly size = input<'sm' | 'md' | 'lg'>('md');
  readonly closed = output<void>();

  protected readonly titleId = `emr-modal-title-${nextModalId++}`;

  constructor() {
    // Backdrop click: the browser reports it with the dialog itself as the event target. Attached in
    // code (not in the template) because it is a pointer-only nicety; Escape is the keyboard path.
    afterNextRender(() =>
      this.dialog().nativeElement.addEventListener('click', (event) => this.onDialogClick(event)),
    );

    // Keeps the native dialog in sync with `open` (a DOM side effect, so effect() is appropriate).
    effect(() => {
      const el = this.dialog().nativeElement;
      if (this.open() && !el.open && typeof el.showModal === 'function') {
        el.showModal();
      } else if (!this.open() && el.open && typeof el.close === 'function') {
        el.close();
      }
    });
  }

  protected close(): void {
    this.open.set(false);
  }

  /** Fired by the browser after any close (Escape, form method=dialog, close()). */
  protected onNativeClose(): void {
    if (this.open()) this.open.set(false);
    this.closed.emit();
  }

  protected onDialogClick(event: MouseEvent): void {
    // A click on the ::backdrop is reported with the dialog itself as the target.
    if (event.target === this.dialog().nativeElement) this.close();
  }
}
