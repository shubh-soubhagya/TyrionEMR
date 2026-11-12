import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { EmrButton } from './button';

@Component({
  imports: [EmrButton],
  template: `
    <button
      emr-button
      id="b"
      [disabled]="disabled()"
      [loading]="loading()"
      (click)="clicks.update((n) => n + 1)"
    >
      Save
    </button>
    <a
      emr-button
      id="a"
      href="#x"
      [disabled]="disabled()"
      (click)="anchorClicks.update((n) => n + 1)"
      >Go</a
    >
  `,
})
class Host {
  readonly disabled = signal(false);
  readonly loading = signal(false);
  readonly clicks = signal(0);
  readonly anchorClicks = signal(0);
}

describe('EmrButton', () => {
  function setup() {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    return {
      fixture,
      host: fixture.componentInstance,
      button: el.querySelector('#b') as HTMLButtonElement,
      anchor: el.querySelector('#a') as HTMLAnchorElement,
    };
  }

  it('emits clicks when enabled', () => {
    const { button, host } = setup();
    button.click();
    expect(host.clicks()).toBe(1);
  });

  it('blocks clicks while disabled', () => {
    const { fixture, host, button, anchor } = setup();
    host.disabled.set(true);
    fixture.detectChanges();

    button.click();
    anchor.click();

    expect(button.disabled).toBe(true);
    expect(host.clicks()).toBe(0);
    expect(anchor.getAttribute('aria-disabled')).toBe('true');
    expect(host.anchorClicks()).toBe(0);
  });

  it('blocks clicks, shows a spinner and sets aria-busy while loading', () => {
    const { fixture, host, button } = setup();
    host.loading.set(true);
    fixture.detectChanges();

    button.click();

    expect(host.clicks()).toBe(0);
    expect(button.disabled).toBe(true);
    expect(button.getAttribute('aria-busy')).toBe('true');
    expect(button.querySelector('emr-spinner')).not.toBeNull();
  });
});
