import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EmrSearchInput } from './search-input';

@Component({
  imports: [EmrSearchInput],
  template: `<emr-search-input
    [(value)]="value"
    (searched)="terms.update((t) => [...t, $event])"
  />`,
})
class Host {
  readonly value = signal('');
  readonly terms = signal<string[]>([]);
}

describe('EmrSearchInput', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function setup() {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const input = (fixture.nativeElement as HTMLElement).querySelector('input') as HTMLInputElement;
    const type = (text: string) => {
      input.value = text;
      input.dispatchEvent(new Event('input'));
    };
    return { fixture, host: fixture.componentInstance, input, type };
  }

  it('emits once, trimmed, after 300 ms of silence', () => {
    const { host, type } = setup();
    type('PT-');
    vi.advanceTimersByTime(200);
    type('  PT-000101 ');
    vi.advanceTimersByTime(299);
    expect(host.terms()).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(host.terms()).toEqual(['PT-000101']);
  });

  it('clears on Escape, emits at once and does not emit again later', () => {
    const { fixture, host, input, type } = setup();
    type('Kulkarni');
    fixture.detectChanges();
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();

    expect(host.value()).toBe('');
    expect(host.terms()).toEqual(['']);
    vi.advanceTimersByTime(1000);
    expect(host.terms()).toEqual(['']);
  });
});
