import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { EmrNonNegative } from './number-keys';

@Component({ imports: [EmrNonNegative], template: `<input type="number" emrNonNegative />` })
class Host {}

describe('EmrNonNegative', () => {
  const press = (key: string): boolean => {
    const f = TestBed.createComponent(Host);
    f.detectChanges();
    const e = new KeyboardEvent('keydown', { key, cancelable: true });
    (f.nativeElement as HTMLElement).querySelector('input')?.dispatchEvent(e);
    return e.defaultPrevented;
  };
  it('blocks the keys that make a number negative or exponential', () => {
    for (const k of ['-', '+', 'e', 'E']) expect(press(k)).toBe(true);
  });
  it('lets digits, the decimal point and editing keys through', () => {
    for (const k of ['5', '.', 'Backspace', 'ArrowUp']) expect(press(k)).toBe(false);
  });
});
