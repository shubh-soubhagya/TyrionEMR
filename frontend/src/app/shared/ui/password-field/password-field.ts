import {
  AfterContentInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  ViewEncapsulation,
  inject,
  signal,
} from '@angular/core';
import { EmrIcon } from '../icon/icon';

/**
 * Wraps one password `<input>` and adds an eye button that shows or hides what was typed (a ⚑ addition: the reference HTML
 * has no such control). The input stays in the page's template, so its reactive-form binding is untouched; this component
 * only flips the input's `type` between `password` and `text`. The button is a real `<button>` with `aria-pressed`.
 */
@Component({
  selector: 'emr-password-field',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None, // the projected input belongs to the page, so its padding is set globally here
  template: `
    <span class="pwf">
      <ng-content />
      <button
        type="button"
        class="pwf-eye"
        [attr.aria-label]="shown() ? 'Hide password' : 'Show password'"
        [attr.aria-pressed]="shown()"
        (click)="toggle()"
      >
        <emr-icon [name]="shown() ? 'eyeOff' : 'eye'" [size]="16" />
      </button>
    </span>
  `,
  styles: `
    emr-password-field {
      display: block;
    }
    emr-password-field .pwf {
      position: relative;
      display: block;
    }
    emr-password-field .pwf input {
      padding-right: 40px;
    }
    emr-password-field .pwf-eye {
      position: absolute;
      top: 50%;
      right: 6px;
      transform: translateY(-50%);
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink-3);
      cursor: pointer;
    }
    emr-password-field .pwf-eye:hover {
      color: var(--ink);
      background: var(--bg);
    }
    emr-password-field .pwf-eye:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px var(--teal-50);
    }
  `,
})
export class EmrPasswordField implements AfterContentInit {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  protected readonly shown = signal(false);
  private input: HTMLInputElement | null = null;

  ngAfterContentInit(): void {
    this.input = this.host.nativeElement.querySelector('input');
  }

  protected toggle(): void {
    this.shown.update((v) => !v);
    if (this.input) this.input.type = this.shown() ? 'text' : 'password';
  }
}
