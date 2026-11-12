import {
  ChangeDetectionStrategy,
  Component,
  booleanAttribute,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { EmrIcon } from '../icon/icon';
import { IconName } from '../icon/icons';

export type AlertTone = 'ok' | 'warn' | 'danger' | 'info';

const ICON: Readonly<Record<AlertTone, IconName>> = {
  ok: 'check',
  warn: 'alert',
  danger: 'alert',
  info: 'info',
};

/** Inline banner (html `.alert`). Errors use role=alert; the rest role=status. */
@Component({
  selector: 'emr-alert',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './alert.html',
  styleUrl: './alert.scss',
  host: {
    '[class]': 'tone()',
    '[attr.role]': "tone() === 'danger' ? 'alert' : 'status'",
    '[hidden]': 'dismissed()',
  },
})
export class EmrAlert {
  readonly tone = input<AlertTone>('info');
  readonly title = input<string>();
  readonly dismissible = input(false, { transform: booleanAttribute });
  readonly dismissed = signal(false);
  readonly closed = output<void>();

  protected readonly icon = computed(() => ICON[this.tone()]);

  protected dismiss(): void {
    this.dismissed.set(true);
    this.closed.emit();
  }
}
