import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ColumnDef, EmrCell, EmrDataTable, TableState } from './data-table';

interface Row {
  id: string;
  name: string;
  egfr: number | null;
}

@Component({
  imports: [EmrDataTable, EmrCell],
  template: `
    <emr-data-table
      label="Patients"
      [columns]="columns"
      [rows]="rows()"
      [state]="state()"
      [rowClickable]="true"
      emptyTitle="No patients match"
      (rowClick)="clicked.set($event.name)"
    >
      <ng-template emrCell="name" [emrCellOf]="rows()" let-row
        ><b class="custom">{{ row.name }}</b></ng-template
      >
    </emr-data-table>
  `,
})
class Host {
  readonly columns: readonly ColumnDef[] = [
    { key: 'id', header: 'Patient ID' },
    { key: 'name', header: 'Name' },
    { key: 'egfr', header: 'eGFR', align: 'end' },
  ];
  readonly rows = signal<Row[]>([
    { id: 'PT-000101', name: 'Ramesh Kulkarni', egfr: 38 },
    { id: 'PT-000108', name: 'Priya Nair', egfr: null },
  ]);
  readonly state = signal<TableState>('ready');
  readonly clicked = signal('');
}

describe('EmrDataTable', () => {
  function setup() {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    return { fixture, host: fixture.componentInstance, el: fixture.nativeElement as HTMLElement };
  }

  it('renders a row per item, using custom cells and "Not documented" for missing values', () => {
    const { el } = setup();
    const rows = el.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    expect(rows[0]?.textContent).toContain('PT-000101');
    expect(rows[0]?.querySelector('.custom')?.textContent).toBe('Ramesh Kulkarni');
    expect(rows[1]?.textContent).toContain('Not documented');
  });

  it('shows the empty state when there are no rows', () => {
    const { fixture, host, el } = setup();
    host.rows.set([]);
    fixture.detectChanges();
    expect(el.querySelector('emr-empty-state')?.textContent).toContain('No patients match');
  });

  it('shows skeleton rows while loading and an error state on error', () => {
    const { fixture, host, el } = setup();
    host.state.set('loading');
    fixture.detectChanges();
    expect(el.querySelectorAll('emr-skeleton').length).toBeGreaterThan(0);
    expect(el.querySelector('table')?.getAttribute('aria-busy')).toBe('true');

    host.state.set('error');
    fixture.detectChanges();
    expect(el.querySelector('emr-error-state')).not.toBeNull();
  });

  it('emits rowClick on click and on Enter', () => {
    const { fixture, host, el } = setup();
    const rows = el.querySelectorAll<HTMLElement>('tbody tr');
    (rows[0] as HTMLElement).click();
    expect(host.clicked()).toBe('Ramesh Kulkarni');

    host.clicked.set('');
    const second = rows[1] as HTMLElement;
    second.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    fixture.detectChanges();
    expect(host.clicked()).toBe('Priya Nair');
    expect(second.getAttribute('tabindex')).toBe('0');
  });
});
