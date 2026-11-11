import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { EmrAvatar } from '@shared/ui/avatar/avatar';
import { EmrIcon } from '@shared/ui/icon/icon';

/** Sticky top bar (html `.topbar`): mobile menu button, global patient search, user menu. */
@Component({
  selector: 'emr-header',
  imports: [EmrIcon, EmrAvatar],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './header.html',
  styleUrl: './header.scss',
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(keydown.escape)': 'closeUserMenu()',
  },
})
export class EmrHeader {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly menuButton = viewChild<ElementRef<HTMLButtonElement>>('menuButton');
  private readonly userButton = viewChild<ElementRef<HTMLButtonElement>>('userButton');

  readonly userName = input.required<string>();
  readonly userRole = input.required<string>();
  /** Whether the mobile navigation drawer is open (for aria-expanded). */
  readonly navOpen = input(false);

  readonly navToggle = output<void>();
  /** Submitted global search text, trimmed. */
  readonly searchSubmit = output<string>();
  readonly signOut = output<void>();

  protected readonly userMenuOpen = signal(false);

  focusMenuButton(): void {
    this.menuButton()?.nativeElement.focus();
  }

  protected submitSearch(event: Event, input: HTMLInputElement): void {
    event.preventDefault();
    this.searchSubmit.emit(input.value.trim());
  }

  protected toggleUserMenu(): void {
    this.userMenuOpen.update((open) => !open);
  }

  protected closeUserMenu(): void {
    if (this.userMenuOpen()) {
      this.userMenuOpen.set(false);
      this.userButton()?.nativeElement.focus();
    }
  }

  protected onSignOut(): void {
    this.userMenuOpen.set(false);
    this.signOut.emit();
  }

  protected onDocumentClick(event: Event): void {
    if (this.userMenuOpen() && !this.host.nativeElement.contains(event.target as Node)) {
      this.userMenuOpen.set(false);
    }
  }
}
