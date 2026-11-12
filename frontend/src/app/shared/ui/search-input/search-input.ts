import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subject, map, switchMap, timer } from 'rxjs';
import { EmrIcon } from '../icon/icon';

/**
 * Search box (html `.toolbar .search`). `searched` fires after the user stops typing for
 * `debounceMs` (default 300) with the trimmed text. Escape or the clear button empties the box
 * and emits at once. `value` is two-way so a page can sync it with the URL.
 */
@Component({
  selector: 'emr-search-input',
  imports: [EmrIcon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './search-input.html',
  styleUrl: './search-input.scss',
})
export class EmrSearchInput {
  readonly label = input('Search');
  readonly placeholder = input('');
  readonly debounceMs = input(300);
  readonly value = model('');
  readonly searched = output<string>();

  // null = cancel the pending debounced emission (used by clear()).
  private readonly typed = new Subject<string | null>();

  constructor() {
    this.typed
      .pipe(
        // The delay is read per keystroke, so the `debounceMs` input can be set after construction.
        // switchMap cancels the previous timer, which is what debouncing means.
        switchMap((text) =>
          text === null ? EMPTY : timer(this.debounceMs()).pipe(map(() => text.trim())),
        ),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe((text) => this.searched.emit(text));
  }

  protected onInput(event: Event): void {
    const text = (event.target as HTMLInputElement).value;
    this.value.set(text);
    this.typed.next(text);
  }

  protected clear(field: HTMLInputElement): void {
    this.value.set('');
    field.value = '';
    // A pending debounced search for the old text must not fire after the clear.
    this.typed.next(null);
    this.searched.emit('');
    field.focus();
  }

  protected onKeydown(event: KeyboardEvent, field: HTMLInputElement): void {
    if (event.key === 'Escape' && this.value()) {
      event.preventDefault();
      this.clear(field);
    }
  }
}
