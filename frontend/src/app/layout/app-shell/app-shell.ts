import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { EmrHeader } from '../header/header';
import { NAV_ITEMS } from '../nav-items';
import { EmrSidebar } from '../sidebar/sidebar';
import { ModalHost } from '../../features/modals/modal-host';
import { EmrTooltip } from '../../shared/ui/tooltip/tooltip';

/** Signed-in frame (html `.shell`): sidebar, sticky top bar, scrolling main content. */
@Component({
  selector: 'emr-app-shell',
  imports: [RouterOutlet, EmrSidebar, EmrHeader, ModalHost, EmrTooltip],
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

  private readonly auth = inject(AuthService);
  protected readonly userName = computed(() => this.auth.user()?.fullName ?? '');
  protected readonly userRole = computed(() => this.auth.user()?.roleLabel ?? '');

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
    // Tell the server to drop the refresh cookie, forget the session, then show the sign-in page.
    this.auth.logout().subscribe(() => void this.router.navigate(['/login']));
  }

  protected skipToMain(event: Event): void {
    event.preventDefault();
    this.main().nativeElement.focus();
  }
}
