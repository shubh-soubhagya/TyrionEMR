// Clinical value types shared by UI components. Codes follow the HTML and the HLD.

export type LabFlag = 'normal' | 'low' | 'high' | 'critical_low' | 'critical_high' | 'unknown';

export type CkdStage = 'G1' | 'G2' | 'G3a' | 'G3b' | 'G4' | 'G5';

/** KDIGO eGFR categories (html:395). Labels are exactly the HTML's. */
export const CKD_STAGE_LABELS: Readonly<Record<CkdStage, string>> = {
  G1: 'Normal or high',
  G2: 'Mildly decreased',
  G3a: 'Mild to moderately decreased',
  G3b: 'Moderately to severely decreased',
  G4: 'Severely decreased',
  G5: 'Kidney failure',
};
