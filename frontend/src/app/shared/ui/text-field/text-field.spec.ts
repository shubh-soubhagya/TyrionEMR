import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { EmrTextField } from './text-field';

@Component({
  imports: [ReactiveFormsModule, EmrTextField],
  template: `<emr-text-field label="Systolic BP" suffix="mmHg" [formControl]="control" />`,
})
class Host {
  readonly control = new FormControl<string | number>('', {
    nonNullable: true,
    validators: [Validators.required],
  });
}

describe('EmrTextField (ControlValueAccessor)', () => {
  function setup() {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    return {
      fixture,
      control: fixture.componentInstance.control,
      input: el.querySelector('input') as HTMLInputElement,
      el,
    };
  }

  it('writes the form value into the input', () => {
    const { fixture, control, input } = setup();
    control.setValue('120');
    fixture.detectChanges();
    expect(input.value).toBe('120');
  });

  it('propagates typing to the form control', () => {
    const { control, input } = setup();
    input.value = '135';
    input.dispatchEvent(new Event('input'));
    expect(control.value).toBe('135');
  });

  it('shows the error only after the control is touched', async () => {
    const { fixture, control, input, el } = setup();
    await fixture.whenStable();
    expect(el.querySelector('.err')).toBeNull();

    input.dispatchEvent(new Event('blur'));
    await fixture.whenStable();
    fixture.detectChanges();

    expect(control.touched).toBe(true);
    expect(el.querySelector('.err')?.textContent).toContain('This field is required.');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('aria-describedby')).toContain('-err');
  });

  it('disables the input when the control is disabled', () => {
    const { fixture, control, input } = setup();
    control.disable();
    fixture.detectChanges();
    expect(input.disabled).toBe(true);
  });
});
