import { Signal, computed, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { Observable, switchMap } from 'rxjs';
import { LOADING, isEmptyValue, toRemote, type Remote } from './remote';

export interface RemoteSignal<T> {
  readonly state: Signal<Remote<T>>;
  /** Loads again (the panel's Retry button, or after a save changed this data). */
  reload(): void;
}

/**
 * A panel's data as a signal of `Remote<T>` (RxJS stays inside; the component sees a signal).
 * It loads when `trigger` changes (an id, a page, a filter) and whenever `reload()` is called; an older request still
 * in flight is cancelled. Call it in an injection context (a field initializer). `load` is called untracked.
 */
export function remoteSignal<T>(
  trigger: () => unknown,
  load: () => Observable<T>,
  isEmpty: (v: T) => boolean = isEmptyValue,
): RemoteSignal<T> {
  const nonce = signal(0);
  const key = computed(() => [trigger(), nonce()] as const);
  const state = toSignal(toObservable(key).pipe(switchMap(() => toRemote(load(), isEmpty))), {
    initialValue: LOADING as Remote<T>,
  });
  return { state, reload: () => nonce.update((n) => n + 1) };
}
