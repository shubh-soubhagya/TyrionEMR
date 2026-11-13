import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideRouter, Router } from '@angular/router';
import { EmrAppShell } from './app-shell';

describe('EmrAppShell', () => {
  let fixture: ComponentFixture<EmrAppShell>;
  let el: HTMLElement;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EmrAppShell],
      providers: [provideHttpClient(), provideRouter([{ path: 'patients', children: [] }])],
    }).compileComponents();
    fixture = TestBed.createComponent(EmrAppShell);
    el = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  });

  it('renders the nav items from the typed config', () => {
    const labels = Array.from(el.querySelectorAll('a.nav-item')).map((a) => a.textContent?.trim());
    expect(labels).toEqual(['Dashboard', 'Patients']);
  });

  it('opens the mobile drawer from the menu button and closes it with Escape', () => {
    const button = el.querySelector<HTMLButtonElement>('.menu-btn');
    expect(el.querySelector('.scrim')).toBeNull();

    button?.click();
    fixture.detectChanges();
    expect(el.querySelector('.scrim')).not.toBeNull();
    expect(el.querySelector('emr-sidebar')?.classList.contains('open')).toBe(true);
    expect(button?.getAttribute('aria-expanded')).toBe('true');

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(el.querySelector('.scrim')).toBeNull();
    expect(button?.getAttribute('aria-expanded')).toBe('false');
  });

  it('opens the user menu with a sign-out action and closes it with Escape', () => {
    const userButton = el.querySelector<HTMLButtonElement>('.user-btn');
    userButton?.click();
    fixture.detectChanges();
    expect(el.querySelector('[role="menuitem"]')?.textContent).toContain('Sign out');

    el.querySelector('emr-header')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();
    expect(el.querySelector('[role="menu"]')).toBeNull();
  });

  it('navigates to /patients?q= when the global search is submitted', async () => {
    const router = TestBed.inject(Router);
    const navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    const input = el.querySelector<HTMLInputElement>('.gsearch input');
    if (!input) throw new Error('search input missing');
    input.value = '  PT-000101  ';
    el.querySelector<HTMLFormElement>('.gsearch')?.dispatchEvent(new Event('submit'));

    expect(navigate).toHaveBeenCalledWith(['/patients'], { queryParams: { q: 'PT-000101' } });
  });
});
