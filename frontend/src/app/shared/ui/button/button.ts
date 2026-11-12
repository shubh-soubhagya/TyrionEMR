import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  booleanAttribute,
  computed,
  inject,
  input,
} from '@angular/core';
import { EmrIcon } from '../icon/icon';
import { IconName } from '../icon/icons';
import { EmrSpinner } from '../spinner/spinner';

export type ButtonVariant = 'default' | 'primary' | 'ai' | 'danger' | 'ghost';

/**
 * Button (html `.btn`). Used as an attribute on a real element so semantics stay native:
 *   <button emr-button variant="primary">Save</button>
 *   <a emr-button routerLink="/patients">Patients</a>
 * While `loading` the button is disabled, shows a spinner and sets aria-busy, so a second
 * click cannot submit twice. A disabled <a> gets aria-disabled and its clicks are swallowed.
 */
@Component({
  // Attribute selector on purpose (native button/anchor semantics), so the element-prefix rule does not apply.
  // eslint-disable-next-line @angular-eslint/component-selector
  selector: 'button[emr-button], a[emr-button]',
  imports: [EmrIcon, EmrSpinner],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './button.html',
  styleUrl: './button.scss',
  host: {
    '[class]': 'classes()',
    '[attr.disabled]': 'blocked() && isButton ? "" : null',
    '[attr.aria-disabled]': 'blocked() ? "true" : null',
    '[attr.aria-busy]': 'loading() ? "true" : null',
    '[attr.tabindex]': 'blocked() && !isButton ? -1 : null',
    '(click)': 'onClick($event)',
  },
})
export class EmrButton {
  readonly variant = input<ButtonVariant>('default');
  readonly size = input<'md' | 'sm'>('md');
  readonly loading = input(false, { transform: booleanAttribute });
  readonly disabled = input(false, { transform: booleanAttribute });
  readonly block = input(false, { transform: booleanAttribute });
  readonly icon = input<IconName>();
  readonly iconEnd = input<IconName>();

  protected readonly isButton =
    inject<ElementRef<HTMLElement>>(ElementRef).nativeElement.tagName === 'BUTTON';
  protected readonly blocked = computed(() => this.disabled() || this.loading());
  protected readonly iconSize = computed(() => (this.size() === 'sm' ? 14 : 16));
  protected readonly classes = computed(
    () =>
      `btn ${this.variant()} ${this.size()}${this.block() ? ' block' : ''}${this.loading() ? ' loading' : ''}`,
  );

  protected onClick(event: Event): void {
    if (this.blocked()) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }
}
