import {
  DestroyRef,
  Directive,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  ControlValueAccessor,
  FormGroupDirective,
  NgControl,
  ValidationErrors,
  Validators,
} from '@angular/forms';

let nextFieldId = 0;

/**
 * Shared behaviour of every emr form control: ControlValueAccessor plumbing plus the rule
 * "show the error only after the control was touched or the form was submitted".
 *
 * It injects NgControl itself (instead of providing NG_VALUE_ACCESSOR) to avoid a circular
 * dependency, and re-renders when the control's state changes, because reactive-forms state is
 * not signal based. T is the value type the control writes to the form.
 */
@Directive()
export abstract class EmrControlBase<T> implements ControlValueAccessor {
  protected readonly ngControl = inject(NgControl, { self: true, optional: true });
  private readonly form = inject(FormGroupDirective, { optional: true });
  private readonly destroyRef = inject(DestroyRef);

  readonly label = input.required<string>();
  readonly hint = input<string>();
  /** Adds the asterisk. Also inferred from `Validators.required` on the control. */
  readonly required = input(false);

  protected readonly uid = `emr-field-${nextFieldId++}`;
  protected readonly hintId = `${this.uid}-hint`;
  protected readonly errorId = `${this.uid}-err`;

  protected readonly value = signal<T | null>(null);
  protected readonly disabled = signal(false);

  /** Bumped whenever the control's status/touched state or the form's submit state changes. */
  private readonly tick = signal(0);

  private onChange: (value: T | null) => void = () => undefined;
  private onTouched: () => void = () => undefined;

  protected readonly errors = computed<ValidationErrors | null>(() => {
    this.tick();
    return this.ngControl?.control?.errors ?? null;
  });

  protected readonly showError = computed(() => {
    this.tick();
    const control = this.ngControl?.control;
    return !!control && control.invalid && (control.touched || !!this.form?.submitted);
  });

  protected readonly isRequired = computed(() => {
    this.tick();
    return this.required() || !!this.ngControl?.control?.hasValidator(Validators.required);
  });

  protected readonly describedBy = computed(() => {
    const ids = [this.hint() ? this.hintId : null, this.showError() ? this.errorId : null];
    return ids.filter(Boolean).join(' ') || null;
  });

  constructor() {
    if (this.ngControl) {
      this.ngControl.valueAccessor = this;
    }
    // The control is attached by the forms directives after construction, so subscribe later.
    afterNextRender(() => {
      const bump = () => this.tick.update((n) => n + 1);
      this.ngControl?.control?.events.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(bump);
      this.form?.ngSubmit.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(bump);
      bump();
    });
  }

  writeValue(value: T | null): void {
    this.value.set(value);
  }

  registerOnChange(fn: (value: T | null) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }

  /** Call from the template when the user changes the value. */
  protected setValue(value: T | null): void {
    this.value.set(value);
    this.onChange(value);
  }

  /** Call from the template on blur. */
  protected markTouched(): void {
    this.onTouched();
  }
}
