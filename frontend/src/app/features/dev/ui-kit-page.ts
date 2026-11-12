import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { CKD_STAGE_LABELS, CkdStage, LabFlag } from '@shared/models/clinical';
import { EmrAlert } from '@shared/ui/alert/alert';
import { EmrAvatar } from '@shared/ui/avatar/avatar';
import { BadgeTone, EmrBadge } from '@shared/ui/badge/badge';
import { EmrButton } from '@shared/ui/button/button';
import { EmrCheckbox } from '@shared/ui/checkbox/checkbox';
import { EmrCkdStageBadge } from '@shared/ui/ckd-stage-badge/ckd-stage-badge';
import { ColumnDef, EmrCell, EmrDataTable, TableState } from '@shared/ui/data-table/data-table';
import { EmrDateField } from '@shared/ui/date-field/date-field';
import { EmrEmptyState } from '@shared/ui/empty-state/empty-state';
import { EmrErrorState } from '@shared/ui/error-state/error-state';
import { EmrIcon } from '@shared/ui/icon/icon';
import { ICONS, IconName } from '@shared/ui/icon/icons';
import { EmrKpiStrip } from '@shared/ui/kpi-strip/kpi-strip';
import { EmrLabFlag } from '@shared/ui/lab-flag/lab-flag';
import { EmrModal } from '@shared/ui/modal/modal';
import { EmrPagination } from '@shared/ui/pagination/pagination';
import { EmrPanel } from '@shared/ui/panel/panel';
import { EmrRadioGroup } from '@shared/ui/radio-group/radio-group';
import { EmrSearchInput } from '@shared/ui/search-input/search-input';
import { EmrSelect, SelectOption } from '@shared/ui/select/select';
import { EmrSkeleton } from '@shared/ui/skeleton/skeleton';
import { EmrSpinner } from '@shared/ui/spinner/spinner';
import { EmrTabs, TabItem } from '@shared/ui/tabs/tabs';
import { EmrTextField } from '@shared/ui/text-field/text-field';
import { EmrTextarea } from '@shared/ui/textarea/textarea';
import { ToastService } from '@shared/ui/toast/toast.service';
import { EmrValueWithUnit } from '@shared/ui/value-with-unit/value-with-unit';
import { EmrPageHeader } from '@layout/page-header/page-header';

interface DemoRow {
  readonly id: string;
  readonly name: string;
  readonly age: number;
  readonly diagnosis: string | null;
  readonly egfr: number | null;
}

/**
 * Dev-only catalogue of every shared component in every variant and state, with hardcoded
 * values, for side-by-side comparison with reference/emr-ui.html. Not routed in production.
 */
@Component({
  selector: 'emr-ui-kit-page',
  imports: [
    ReactiveFormsModule,
    EmrPageHeader,
    EmrAlert,
    EmrAvatar,
    EmrBadge,
    EmrButton,
    EmrCheckbox,
    EmrCkdStageBadge,
    EmrDataTable,
    EmrCell,
    EmrDateField,
    EmrEmptyState,
    EmrErrorState,
    EmrIcon,
    EmrKpiStrip,
    EmrLabFlag,
    EmrModal,
    EmrPagination,
    EmrPanel,
    EmrRadioGroup,
    EmrSearchInput,
    EmrSelect,
    EmrSkeleton,
    EmrSpinner,
    EmrTabs,
    EmrTextField,
    EmrTextarea,
    EmrValueWithUnit,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './ui-kit-page.html',
  styleUrl: './ui-kit-page.scss',
})
export class UiKitPage {
  private readonly fb = inject(FormBuilder).nonNullable;
  protected readonly toast = inject(ToastService);

  protected readonly tones: readonly BadgeTone[] = [
    'neutral',
    'ok',
    'warn',
    'danger',
    'info',
    'teal',
    'ai',
  ];
  protected readonly flags: readonly LabFlag[] = [
    'normal',
    'low',
    'high',
    'critical_low',
    'critical_high',
    'unknown',
  ];
  protected readonly stages = Object.keys(CKD_STAGE_LABELS) as CkdStage[];
  protected readonly iconNames = Object.keys(ICONS) as IconName[];

  protected readonly kpis = [
    { label: 'Patients', value: 10 },
    { label: 'Need attention', value: 4, hot: true },
    { label: 'With critical results', value: 1 },
    { label: 'Rapid eGFR decline', value: 2 },
    { label: 'Draft encounters', value: 1 },
  ];

  protected readonly tabs: readonly TabItem[] = [
    { key: 'overview', label: 'Overview', icon: 'user' },
    { key: 'conditions', label: 'Conditions', icon: 'clip', count: 4 },
    { key: 'labs', label: 'Labs', icon: 'flask', count: 8 },
    { key: 'ai', label: 'AI summary', icon: 'spark', tone: 'ai' },
  ];
  protected readonly tab = signal('overview');

  protected readonly sexOptions: readonly SelectOption[] = [
    { value: 'M', label: 'Male' },
    { value: 'F', label: 'Female' },
    { value: 'O', label: 'Other' },
  ];

  protected readonly columns: readonly ColumnDef[] = [
    { key: 'id', header: 'Patient ID', nowrap: true, sortable: true },
    { key: 'name', header: 'Name', sortable: true },
    { key: 'age', header: 'Age', align: 'end' },
    { key: 'diagnosis', header: 'Primary diagnosis' },
    { key: 'egfr', header: 'Latest eGFR', align: 'end' },
  ];
  protected readonly rows: readonly DemoRow[] = [
    {
      id: 'PT-000101',
      name: 'Ramesh Kulkarni',
      age: 67,
      diagnosis: 'Diabetic nephropathy',
      egfr: 38,
    },
    { id: 'PT-000102', name: 'Sunita Verma', age: 58, diagnosis: 'Hypertensive CKD', egfr: 55 },
    { id: 'PT-000108', name: 'Priya Nair', age: 50, diagnosis: null, egfr: null },
  ];
  protected readonly tableState = signal<TableState>('ready');
  protected readonly showRows = signal(true);
  protected readonly rowKey = (row: DemoRow): string => row.id;
  protected readonly clicked = signal('');
  protected readonly page = signal(1);
  protected readonly search = signal('');
  protected readonly modalOpen = signal(false);
  protected readonly demoButtonBusy = signal(false);

  protected readonly form = this.fb.group({
    name: ['', Validators.required],
    sbp: [null as number | null, [Validators.required, Validators.min(60), Validators.max(260)]],
    sex: ['F'],
    notes: [''],
    visit: ['2026-11-11'],
    confirm: [false],
    type: ['follow_up'],
  });
  protected readonly typeOptions: readonly SelectOption[] = [
    { value: 'new', label: 'New visit' },
    { value: 'follow_up', label: 'Follow-up' },
    { value: 'emergency', label: 'Emergency' },
  ];

  protected submitForm(): void {
    this.form.markAllAsTouched();
  }

  protected simulateSave(): void {
    this.demoButtonBusy.set(true);
    setTimeout(() => this.demoButtonBusy.set(false), 1500);
  }
}
