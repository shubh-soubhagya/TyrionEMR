import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  input,
  model,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { EmrIcon } from '../icon/icon';
import { IconName } from '../icon/icons';

export interface TabItem {
  readonly key: string;
  readonly label: string;
  readonly icon?: IconName;
  /** Count pill (html `.ct`). */
  readonly count?: number;
  /** Violet active state for the AI tab. */
  readonly tone?: 'ai';
  /** Router link: when set the tab is a link (router-driven mode). */
  readonly link?: string | readonly string[];
}

/**
 * Accessible tab bar (html `.tabs`). Two modes:
 *  - local: tabs are buttons, `selected` (two-way) holds the key, arrow keys also select;
 *  - router: tabs have `link`, the active route marks the tab; arrow keys move focus and Enter
 *    follows the link.
 * Arrow Left/Right, Home and End move between tabs (roving tabindex). `panelId` is the id of the
 * panel the tabs control (aria-controls).
 */
@Component({
  selector: 'emr-tabs',
  imports: [EmrIcon, RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './tabs.html',
  styleUrl: './tabs.scss',
  host: { '(keydown)': 'onKeydown($event)' },
})
export class EmrTabs {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly tabs = input.required<readonly TabItem[]>();
  readonly label = input('Sections');
  readonly panelId = input<string>();
  readonly selected = model<string>();

  protected onKeydown(event: KeyboardEvent): void {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();

    const list = this.tabs();
    const buttons = Array.from(this.host.nativeElement.querySelectorAll<HTMLElement>('[role=tab]'));
    const current = buttons.findIndex((el) => el === document.activeElement);
    let next = current < 0 ? 0 : current;
    if (event.key === 'ArrowRight') next = (current + 1) % list.length;
    if (event.key === 'ArrowLeft') next = (current - 1 + list.length) % list.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = list.length - 1;

    buttons[next]?.focus();
    const target = list[next];
    if (target && !target.link) {
      this.selected.set(target.key);
    }
  }

  protected select(tab: TabItem): void {
    if (!tab.link) this.selected.set(tab.key);
  }
}
