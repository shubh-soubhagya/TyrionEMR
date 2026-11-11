import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/** Initials avatar (html `.avatar`, `avatar()` helper): first letters of up to two words. */
@Component({
  selector: 'emr-avatar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `{{ initials() }}`,
  host: { '[class.lg]': "size() === 'lg'", 'aria-hidden': 'true' },
  styleUrl: './avatar.scss',
})
export class EmrAvatar {
  readonly name = input.required<string>();
  readonly size = input<'md' | 'lg'>('md');

  protected readonly initials = computed(() =>
    this.name()
      .split(' ')
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0])
      .join('')
      .toUpperCase(),
  );
}
