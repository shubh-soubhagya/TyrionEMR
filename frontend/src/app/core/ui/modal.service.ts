import { Injectable, signal } from '@angular/core';

export type ModalState =
  | { kind: 'patient'; patientId: string | null }
  | { kind: 'condition'; patientId: string }
  | { kind: 'med'; patientId: string }
  | { kind: 'allergy'; patientId: string }
  | { kind: 'encounter-form'; patientId: string; encounterId: string | null }
  | { kind: 'encounter-view'; encounterId: string; sub: string }
  | { kind: 'lab'; patientId: string }
  | {
      kind: 'confirm';
      title: string;
      message: string;
      ok: string;
      danger: boolean;
    };

/** Which modal is open (html `openModal` / `confirmDialog`). Rendered by `emr-modal-host`. */
@Injectable({ providedIn: 'root' })
export class ModalService {
  readonly current = signal<ModalState | null>(null);
  private confirmResolve: ((ok: boolean) => void) | null = null;

  open(state: ModalState): void {
    this.close();
    this.current.set(state);
  }

  close(): void {
    this.current.set(null);
    if (this.confirmResolve) {
      this.confirmResolve(false);
      this.confirmResolve = null;
    }
  }

  confirm(opts: { title: string; message: string; ok?: string; danger?: boolean }): Promise<boolean> {
    this.close();
    return new Promise((resolve) => {
      this.confirmResolve = resolve;
      this.current.set({
        kind: 'confirm',
        title: opts.title,
        message: opts.message,
        ok: opts.ok ?? 'Confirm',
        danger: !!opts.danger,
      });
    });
  }

  answerConfirm(ok: boolean): void {
    const resolve = this.confirmResolve;
    this.confirmResolve = null;
    this.current.set(null);
    resolve?.(ok);
  }
}
