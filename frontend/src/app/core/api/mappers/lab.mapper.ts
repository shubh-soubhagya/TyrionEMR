// lab-svc DTO -> view model. Pure functions.
import type { Flag, TestCode } from '../../clinical/lab-tests';
import type { LabResult } from '../../data/models';
import type { ResultDto } from '../dto/lab.dto';

const FLAGS: readonly Flag[] = [
  'normal',
  'low',
  'high',
  'critical_low',
  'critical_high',
  'unknown',
];

export function flagFromDto(f: string): Flag {
  return (FLAGS as readonly string[]).includes(f) ? (f as Flag) : 'unknown';
}

export function labResultFromDto(d: ResultDto, patientId: string): LabResult {
  return {
    id: d.id,
    reportId: d.report_id,
    patientId,
    collectedAt: d.collected_at,
    test: d.test_code as TestCode,
    value: d.value,
    unit: d.unit,
    valueOriginal: d.value_original,
    unitOriginal: d.unit_original,
    refLow: d.ref_low,
    refHigh: d.ref_high,
    flag: flagFromDto(d.flag),
  };
}
