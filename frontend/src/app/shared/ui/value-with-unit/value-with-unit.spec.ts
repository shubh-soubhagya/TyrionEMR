import { TestBed } from '@angular/core/testing';
import { EmrValueWithUnit } from './value-with-unit';

describe('EmrValueWithUnit', () => {
  function render(inputs: Record<string, unknown>): string {
    const fixture = TestBed.createComponent(EmrValueWithUnit);
    for (const [key, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(key, value);
    }
    fixture.detectChanges();
    return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  it('shows "Not documented" for null, undefined and empty text', () => {
    expect(render({ value: null, unit: 'mg/dL' })).toBe('Not documented');
    expect(render({ value: undefined })).toBe('Not documented');
    expect(render({ value: '  ' })).toBe('Not documented');
  });

  it('shows the value with its unit', () => {
    expect(render({ value: 1.9, unit: 'mg/dL', decimals: 2 })).toBe('1.90 mg/dL');
  });

  it('treats 0 as a real value, not as missing', () => {
    expect(render({ value: 0, unit: 'mmol/L' })).toBe('0 mmol/L');
  });
});
