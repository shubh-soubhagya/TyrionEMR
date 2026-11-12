import { Injectable, signal } from '@angular/core';

export type ToastType = 'ok' | 'err' | 'info';

export interface Toast {
  readonly id: number;
  readonly type: ToastType;
  readonly message: string;
}

/**
 * Transient messages (html `toast()`): shown 3.4 s, errors 5.2 s. The container announces them
 * through an aria-live region.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private nextId = 0;
  private readonly list = signal<readonly Toast[]>([]);
  readonly toasts = this.list.asReadonly();

  show(message: string, type: ToastType = 'ok'): void {
    const id = this.nextId++;
    this.list.update((all) => [...all, { id, type, message }]);
    setTimeout(() => this.dismiss(id), type === 'err' ? 5200 : 3400);
  }

  success(message: string): void {
    this.show(message, 'ok');
  }

  error(message: string): void {
    this.show(message, 'err');
  }

  info(message: string): void {
    this.show(message, 'info');
  }

  dismiss(id: number): void {
    this.list.update((all) => all.filter((t) => t.id !== id));
  }
}
