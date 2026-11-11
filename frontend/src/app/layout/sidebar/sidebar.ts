import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  input,
  output,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { EmrIcon } from '@shared/ui/icon/icon';
import { NavItem } from '../nav-items';

/**
 * Dark left navigation (html `.sidebar`). On narrow screens it is hidden, and becomes a slide-over
 * drawer when `open` is true (the HTML has no mobile navigation; this is our addition).
 */
@Component({
  selector: 'emr-sidebar',
  imports: [RouterLink, RouterLinkActive, EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.scss',
  host: { '[class.open]': 'open()' },
})
export class EmrSidebar {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly items = input.required<readonly NavItem[]>();
  readonly open = input(false);
  /** Emitted when a nav link is followed, so the shell can close the mobile drawer. */
  readonly navigated = output<void>();

  focusFirstLink(): void {
    this.host.nativeElement.querySelector<HTMLElement>('a.nav-item')?.focus();
  }
}
