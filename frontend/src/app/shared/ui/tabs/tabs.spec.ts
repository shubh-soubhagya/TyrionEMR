import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { EmrTabs, TabItem } from './tabs';

@Component({
  imports: [EmrTabs],
  template: `<emr-tabs [tabs]="tabs" [(selected)]="selected" label="Demo" />`,
})
class Host {
  readonly tabs: readonly TabItem[] = [
    { key: 'a', label: 'Overview' },
    { key: 'b', label: 'Labs' },
    { key: 'c', label: 'AI summary' },
  ];
  readonly selected = signal('a');
}

describe('EmrTabs', () => {
  function setup() {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const tabs = () => Array.from(el.querySelectorAll<HTMLElement>('[role=tab]'));
    const list = el.querySelector('[role=tablist]') as HTMLElement;
    return { fixture, host: fixture.componentInstance, tabs, list };
  }

  const press = (list: HTMLElement, key: string) =>
    list.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));

  it('exposes tablist semantics with a roving tabindex', () => {
    const { tabs, list } = setup();
    expect(list.getAttribute('aria-label')).toBe('Demo');
    expect(tabs().map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false']);
    expect(tabs().map((t) => t.getAttribute('tabindex'))).toEqual(['0', '-1', '-1']);
  });

  it('moves selection with the arrow keys (wrapping) and Home/End', () => {
    const { fixture, host, tabs, list } = setup();
    tabs()[0]?.focus();

    press(list, 'ArrowRight');
    fixture.detectChanges();
    expect(host.selected()).toBe('b');

    press(list, 'ArrowRight');
    press(list, 'ArrowRight'); // wraps to the first tab
    fixture.detectChanges();
    expect(host.selected()).toBe('a');

    press(list, 'ArrowLeft'); // wraps to the last tab
    fixture.detectChanges();
    expect(host.selected()).toBe('c');

    press(list, 'Home');
    fixture.detectChanges();
    expect(host.selected()).toBe('a');

    press(list, 'End');
    fixture.detectChanges();
    expect(host.selected()).toBe('c');
    expect(tabs()[2]?.getAttribute('aria-selected')).toBe('true');
  });
});
