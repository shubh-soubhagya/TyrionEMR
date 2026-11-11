import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { EmrHeader } from '../header/header';
import { NAV_ITEMS } from '../nav-items';
import { EmrSidebar } from '../sidebar/sidebar';

/** Signed-in frame (html `.shell`): sidebar, sticky top bar, scrolling main content. */
@Component({
  selector: 'emr-app-shell',
  imports: [RouterOutlet, EmrSidebar, EmrHeader],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app-shell.html',
  styleUrl: './app-shell.scss',
  host: { '(document:keydown.escape)': 'onEscape()' },
})
export class EmrAppShell {
  private readonly router = inject(Router);
  private readonly main = viewChild.required<ElementRef<HTMLElement>>('main');
  private readonly sidebar = viewChild.required(EmrSidebar);
  private readonly header = viewChild.required(EmrHeader);

  protected readonly navItems = NAV_ITEMS;
  protected readonly navOpen = signal(false);

  // Placeholder identity (synthetic clinician from the prototype). Phase 5 replaces these with
  // the signed-in user from AuthService, and signOut() with a real logout.
  protected readonly userName = 'Dr. Anita Rao';
  protected readonly userRole = 'Nephrologist';

  protected toggleNav(): void {
    const opening = !this.navOpen();
    this.navOpen.set(opening);
    if (opening) {
      // Move focus into the drawer once it is rendered.
      queueMicrotask(() => this.sidebar().focusFirstLink());
    }
  }

  protected closeNav(): void {
    this.navOpen.set(false);
  }

  protected onEscape(): void {
    if (this.navOpen()) {
      this.closeNav();
      this.header().focusMenuButton();
    }
  }

  protected search(term: string): void {
    void this.router.navigate(['/patients'], { queryParams: term ? { q: term } : {} });
  }

  protected signOut(): void {
    // Wired in Phase 5 (auth). Intentionally a no-op for now.
  }

  protected skipToMain(event: Event): void {
    event.preventDefault();
    this.main().nativeElement.focus();
  }
}
