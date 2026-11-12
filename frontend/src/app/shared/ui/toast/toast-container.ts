import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { EmrIcon } from '../icon/icon';
import { IconName } from '../icon/icons';
import { ToastService, ToastType } from './toast.service';

const ICON: Readonly<Record<ToastType, IconName>> = { ok: 'check', err: 'alert', info: 'info' };

/** Bottom-right stack of toasts (html `#toasts`, `.toast`). Mount once in the app root. */
@Component({
  selector: 'emr-toast-container',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="stack" aria-live="polite">
      @for (toast of service.toasts(); track toast.id) {
        <div class="toast" [class]="toast.type">
          <emr-icon [name]="icon[toast.type]" [size]="16" />
          <span>{{ toast.message }}</span>
        </div>
      }
    </div>
  `,
  styleUrl: './toast-container.scss',
})
export class EmrToastContainer {
  protected readonly service = inject(ToastService);
  protected readonly icon = ICON;
}
