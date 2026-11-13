import { Injectable, signal } from '@angular/core';

/** What a modal just saved, so the page behind it reloads exactly that data (not the whole page). */
export type ChangeKind =
  'patient' | 'conditions' | 'medications' | 'allergies' | 'encounters' | 'labs';

export interface Change {
  readonly kind: ChangeKind;
  readonly patientId: string;
  /** Increases with every change, so two saves in a row are two events. */
  readonly n: number;
}

export type ModalState =
  | { kind: 'patient'; patientId: string | null }
  | { kind: 'condition'; patientId: string }
  | { kind: 'med'; patientId: string }
  | { kind: 'allergy'; patientId: string }
  | { kind: 'encounter-form'; patientId: string; encounterId: string | null }
  | { kind: 'encounter-view'; patientId: string; encounterId: string; sub: string }
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
  /** The last save; pages that show that data watch it and reload it. */
  readonly changed = signal<Change | null>(null);
  private changeCount = 0;
  private confirmResolve: ((ok: boolean) => void) | null = null;

  open(state: ModalState): void {
    this.close();
    this.current.set(state);
  }

  notifyChanged(kind: ChangeKind, patientId: string): void {
    this.changed.set({ kind, patientId, n: ++this.changeCount });
  }

  close(): void {
    this.current.set(null);
    if (this.confirmResolve) {
      this.confirmResolve(false);
      this.confirmResolve = null;
    }
  }

  confirm(opts: {
    title: string;
    message: string;
    ok?: string;
    danger?: boolean;
  }): Promise<boolean> {
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
