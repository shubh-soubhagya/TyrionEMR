// Port of the HTML's synthetic seed (html:417-524). Same ten patients, same values, same seeded
// random generator, so the Angular screens show exactly what the prototype shows.
import { creatFromEgfr, flagFor, LAB_TESTS, rangeFor, Sex } from '../clinical/lab-tests';
import { DAY, isoDate, mulberry32, uid } from '../format';
import { CkdStage, Db, EncounterType } from './models';

type CondTuple = [string, string, 'nephrology' | 'comorbidity', 0 | 1, number];
type MedTuple = [string, string, string, string, number, number | null];
type EncTuple = [
  number,
  EncounterType,
  string,
  string[],
  string,
  string,
  string,
  [number, number, number, number, number] | null,
  'draft' | 'final',
  number,
];
interface LabSpec {
  n: number;
  e0: number;
  e1: number;
  span: number;
  last: number;
  K: number;
  Kl?: number;
  HB: number;
  CA: number;
  PHOS: number;
  UACR: number;
  conv?: number;
  bump?: number;
}
interface Spec {
  first: string;
  last: string;
  sex: Sex;
  age: number;
  ckd: CkdStage | null;
  als: 'has' | 'unknown' | 'nka';
  al: [string, string, 'mild' | 'moderate' | 'severe'][];
  pmh: string;
  fh: string;
  sh: string;
  c: CondTuple[];
  m: MedTuple[];
  L: LabSpec | null;
  e: EncTuple[];
}

const SPECS: Spec[] = [
  {
    first: 'Ramesh',
    last: 'Kulkarni',
    sex: 'M',
    age: 67,
    ckd: 'G3b',
    als: 'has',
    al: [['Penicillin', 'Rash', 'moderate']],
    pmh: 'Type 2 diabetes for 18 years. Hypertension for 15 years. Diabetic retinopathy treated with laser in 2022.',
    fh: 'Father had end-stage kidney disease.',
    sh: 'Retired bank manager. Non-smoker. No alcohol.',
    c: [
      ['E11.21', 'Type 2 diabetes mellitus with diabetic nephropathy', 'nephrology', 1, 18],
      ['N18.32', 'Chronic kidney disease, stage 3b', 'nephrology', 0, 3],
      ['I10', 'Essential hypertension', 'comorbidity', 0, 15],
      ['D63.1', 'Anemia in chronic kidney disease', 'comorbidity', 0, 1],
    ],
    m: [
      ['Losartan', '50 mg', 'Oral', 'Once daily', 700, null],
      ['Empagliflozin', '10 mg', 'Oral', 'Once daily', 400, null],
      ['Atorvastatin', '20 mg', 'Oral', 'Once daily at night', 900, null],
      ['Insulin glargine', '18 units', 'SC', 'Once daily at night', 1200, null],
    ],
    L: {
      n: 8,
      e0: 54,
      e1: 38,
      span: 700,
      last: 20,
      K: 5.2,
      HB: 11.6,
      CA: 9.0,
      PHOS: 4.4,
      UACR: 480,
      conv: 3,
    },
    e: [
      [
        260,
        'follow_up',
        'Routine follow-up; mild ankle swelling',
        ['Ankle swelling', 'Fatigue'],
        'BP 148/86. Mild pitting edema at both ankles. Chest clear.',
        'Diabetic nephropathy with progressive CKD G3b. Persistent albuminuria. BP above target.',
        'Continue current therapy. Repeat eGFR, UACR and potassium in 3 months. Salt restriction reinforced.',
        [148, 86, 78, 36.7, 74.5],
        'final',
        90,
      ],
      [
        120,
        'follow_up',
        'Follow-up after labs; reduced appetite',
        ['Reduced appetite', 'Nausea'],
        'BP 142/84. No edema. Euvolemic.',
        'CKD G3b with faster than expected eGFR decline. Hb 11.8 g/dL.',
        'Review anemia parameters. Reinforce glycemic control. Repeat labs in 8 weeks.',
        [142, 84, 76, 36.6, 73.8],
        'final',
        60,
      ],
      [
        21,
        'follow_up',
        'Review of recent laboratory results',
        ['Fatigue'],
        'BP 138/82. Mild pallor.',
        'Persistent eGFR decline over two years; UACR in the severely increased range.',
        'Discuss progression and renal replacement counselling at next visit. Follow-up in 6 weeks.',
        [138, 82, 74, 36.6, 72.9],
        'final',
        42,
      ],
      [
        2,
        'follow_up',
        'Dietitian referral discussion',
        ['Mild nausea'],
        '',
        '',
        '',
        null,
        'draft',
        30,
      ],
    ],
  },
  {
    first: 'Sunita',
    last: 'Verma',
    sex: 'F',
    age: 58,
    ckd: 'G3a',
    als: 'has',
    al: [['Sulfonamides', 'Hives', 'moderate']],
    pmh: 'Hypertension for 12 years. Hyperlipidemia.',
    fh: 'Mother had hypertension.',
    sh: 'School teacher. Non-smoker.',
    c: [
      ['I12.9', 'Hypertensive chronic kidney disease with stage 1-4 CKD', 'nephrology', 1, 9],
      ['N18.31', 'Chronic kidney disease, stage 3a', 'nephrology', 0, 3],
      ['E78.5', 'Hyperlipidemia', 'comorbidity', 0, 6],
    ],
    m: [
      ['Amlodipine', '5 mg', 'Oral', 'Once daily', 800, null],
      ['Losartan', '100 mg', 'Oral', 'Once daily', 800, null],
      ['Atorvastatin', '10 mg', 'Oral', 'Once daily at night', 600, null],
    ],
    L: {
      n: 7,
      e0: 58,
      e1: 55,
      span: 800,
      last: 35,
      K: 4.6,
      HB: 12.6,
      CA: 9.4,
      PHOS: 3.8,
      UACR: 120,
    },
    e: [
      [
        190,
        'follow_up',
        'Routine review',
        ['None reported'],
        'BP 134/80. No edema.',
        'Hypertensive nephropathy, CKD G3a, stable.',
        'Continue antihypertensives. Repeat labs in 6 months.',
        [134, 80, 72, 36.6, 66.2],
        'final',
        180,
      ],
      [
        34,
        'follow_up',
        'Routine review',
        ['None reported'],
        'BP 130/78.',
        'Stable CKD G3a. BP at target.',
        'Continue current plan. Next review in 6 months.',
        [130, 78, 70, 36.5, 66],
        'final',
        180,
      ],
    ],
  },
  {
    first: 'Arjun',
    last: 'Mehta',
    sex: 'M',
    age: 45,
    ckd: 'G2',
    als: 'unknown',
    al: [],
    pmh: 'IgA nephropathy diagnosed by biopsy 6 years ago. Hypertension.',
    fh: 'No known kidney disease.',
    sh: 'Software engineer. Occasional alcohol.',
    c: [
      ['N02.8', 'IgA nephropathy', 'nephrology', 1, 6],
      ['N18.2', 'Chronic kidney disease, stage 2', 'nephrology', 0, 2],
      ['I10', 'Essential hypertension', 'comorbidity', 0, 4],
    ],
    m: [['Ramipril', '5 mg', 'Oral', 'Once daily', 700, null]],
    L: {
      n: 6,
      e0: 82,
      e1: 78,
      span: 600,
      last: 50,
      K: 4.3,
      HB: 14.5,
      CA: 9.6,
      PHOS: 3.4,
      UACR: 210,
    },
    e: [
      [
        240,
        'follow_up',
        'Routine review',
        ['None reported'],
        'BP 126/78.',
        'IgA nephropathy, stable eGFR with moderate albuminuria.',
        'Continue ramipril. Repeat UACR in 4 months.',
        null,
        'final',
        120,
      ],
      [
        49,
        'follow_up',
        'Review of recent labs',
        ['Mild fatigue'],
        'BP 124/76.',
        'Stable.',
        'Continue current plan.',
        [124, 76, 68, 36.6, 81],
        'final',
        120,
      ],
    ],
  },
  {
    first: 'Fatima',
    last: 'Sheikh',
    sex: 'F',
    age: 72,
    ckd: 'G4',
    als: 'has',
    al: [
      ['NSAIDs', 'Worsening renal function', 'severe'],
      ['Iodinated contrast', 'Rash', 'mild'],
    ],
    pmh: 'Type 2 diabetes for 14 years. Long-standing hypertension. Anemia and secondary hyperparathyroidism of CKD.',
    fh: 'Sister has diabetes.',
    sh: 'Lives with daughter. Non-smoker.',
    c: [
      ['N18.4', 'Chronic kidney disease, stage 4', 'nephrology', 1, 5],
      ['E11.21', 'Type 2 diabetes mellitus with diabetic nephropathy', 'nephrology', 0, 14],
      ['D63.1', 'Anemia in chronic kidney disease', 'comorbidity', 0, 2],
      ['N25.81', 'Secondary hyperparathyroidism of renal origin', 'comorbidity', 0, 1],
      ['I10', 'Essential hypertension', 'comorbidity', 0, 20],
    ],
    m: [
      ['Amlodipine', '10 mg', 'Oral', 'Once daily', 900, null],
      ['Calcium acetate', '667 mg', 'Oral', 'Three times daily with meals', 300, null],
      ['Sodium bicarbonate', '500 mg', 'Oral', 'Twice daily', 400, null],
      ['Darbepoetin alfa', '40 mcg', 'SC', 'Every 2 weeks', 200, null],
    ],
    L: {
      n: 7,
      e0: 34,
      e1: 24,
      span: 540,
      last: 12,
      K: 5.4,
      Kl: 5.5,
      HB: 9.8,
      CA: 8.2,
      PHOS: 5.6,
      UACR: 650,
    },
    e: [
      [
        200,
        'follow_up',
        'Fatigue and poor appetite',
        ['Fatigue', 'Poor appetite', 'Itching'],
        'BP 152/88. Pallor. Trace edema.',
        'CKD G4 with anemia and mineral bone disorder.',
        'Adjust ESA plan. Phosphate binder with meals. Labs in 4 weeks.',
        [152, 88, 80, 36.5, 58.3],
        'final',
        30,
      ],
      [
        70,
        'follow_up',
        'Follow-up',
        ['Fatigue'],
        'BP 148/86. Mild pallor.',
        'Progressive CKD G4. Hb remains low.',
        'Continue plan. Discuss dialysis education class.',
        [148, 86, 78, 36.6, 57.9],
        'final',
        30,
      ],
      [
        12,
        'follow_up',
        'Review of results',
        ['Fatigue', 'Itching'],
        'BP 146/84.',
        'Continued decline in eGFR. Potassium and phosphorus elevated.',
        'Dietary potassium and phosphate counselling. Repeat labs in 3 weeks.',
        [146, 84, 76, 36.6, 57.5],
        'final',
        21,
      ],
    ],
  },
  {
    first: 'Vikram',
    last: 'Rao',
    sex: 'M',
    age: 39,
    ckd: null,
    als: 'nka',
    al: [],
    pmh: 'Acute kidney injury after a diarrheal illness with dehydration, 5 months ago. Obesity.',
    fh: 'None documented.',
    sh: 'Sales manager. Non-smoker.',
    c: [
      ['N17.9', 'Acute kidney failure, unspecified (resolving)', 'nephrology', 1, 0.4],
      ['E66.9', 'Obesity', 'comorbidity', 0, 5],
    ],
    m: [],
    L: {
      n: 4,
      e0: 30,
      e1: 74,
      span: 150,
      last: 14,
      K: 4.4,
      HB: 13.9,
      CA: 9.2,
      PHOS: 3.6,
      UACR: 40,
    },
    e: [
      [
        150,
        'new',
        'Reduced urine output and fatigue after diarrheal illness',
        ['Reduced urine output', 'Fatigue', 'Vomiting'],
        'BP 100/62. Dry mucous membranes.',
        'Acute kidney injury, likely pre-renal.',
        'Hospital admission for IV fluids. Daily creatinine.',
        [100, 62, 104, 37.1, 92],
        'final',
        14,
      ],
      [
        14,
        'follow_up',
        'Recovery follow-up',
        ['None reported'],
        'BP 122/78. Euvolemic.',
        'AKI recovering, eGFR improving.',
        'Repeat renal function in 3 months to confirm recovery.',
        [122, 78, 72, 36.6, 90.5],
        'final',
        90,
      ],
    ],
  },
  {
    first: 'Lakshmi',
    last: 'Iyer',
    sex: 'F',
    age: 63,
    ckd: 'G4',
    als: 'nka',
    al: [],
    pmh: 'Autosomal dominant polycystic kidney disease. Hypertension.',
    fh: 'Mother and brother have polycystic kidney disease.',
    sh: 'Homemaker. Non-smoker.',
    c: [
      ['Q61.2', 'Polycystic kidney disease, adult type', 'nephrology', 1, 12],
      ['N18.32', 'Chronic kidney disease, stage 3b', 'nephrology', 0, 2],
      ['I10', 'Essential hypertension', 'comorbidity', 0, 10],
    ],
    m: [
      ['Telmisartan', '40 mg', 'Oral', 'Once daily', 900, null],
      ['Amlodipine', '5 mg', 'Oral', 'Once daily', 500, null],
    ],
    L: {
      n: 6,
      e0: 44,
      e1: 38,
      span: 700,
      last: 28,
      K: 4.8,
      HB: 12.2,
      CA: 9.1,
      PHOS: 4.0,
      UACR: 55,
    },
    e: [
      [
        160,
        'follow_up',
        'Flank discomfort',
        ['Flank pain'],
        'BP 136/82. Palpable kidneys bilaterally.',
        'ADPKD with CKD. Pain likely cyst-related.',
        'Analgesia advice, hydration. Repeat labs in 3 months.',
        [136, 82, 74, 36.6, 64],
        'final',
        90,
      ],
      [
        27,
        'follow_up',
        'Review of results',
        ['None reported'],
        'BP 132/80.',
        'Slow eGFR decline.',
        'Continue current plan.',
        [132, 80, 72, 36.6, 63.8],
        'final',
        90,
      ],
    ],
  },
  {
    first: 'Mohan',
    last: 'Das',
    sex: 'M',
    age: 55,
    ckd: 'G2',
    als: 'nka',
    al: [],
    pmh: 'Type 2 diabetes for 9 years. Hyperlipidemia.',
    fh: 'Father had type 2 diabetes.',
    sh: 'Shop owner. Smokes occasionally.',
    c: [
      ['E11.21', 'Type 2 diabetes mellitus with diabetic nephropathy', 'nephrology', 1, 3],
      ['E78.5', 'Hyperlipidemia', 'comorbidity', 0, 5],
    ],
    m: [
      ['Metformin', '500 mg', 'Oral', 'Twice daily', 900, null],
      ['Dapagliflozin', '10 mg', 'Oral', 'Once daily', 500, null],
      ['Telmisartan', '40 mg', 'Oral', 'Once daily', 500, null],
    ],
    L: {
      n: 5,
      e0: 76,
      e1: 72,
      span: 500,
      last: 230,
      K: 4.5,
      HB: 14.1,
      CA: 9.5,
      PHOS: 3.5,
      UACR: 85,
      bump: 16,
    },
    e: [
      [
        240,
        'follow_up',
        'Routine diabetic kidney review',
        ['None reported'],
        'BP 130/80.',
        'Early diabetic kidney disease, moderately increased albuminuria.',
        'Continue SGLT2 inhibitor and ARB. Repeat labs in 3 months.',
        [130, 80, 76, 36.6, 82],
        'final',
        90,
      ],
      [
        232,
        'follow_up',
        'Lab review',
        ['None reported'],
        'BP 128/78.',
        'Stable.',
        'Next review in 3 months (not yet scheduled).',
        [128, 78, 74, 36.6, 81.5],
        'final',
        90,
      ],
    ],
  },
  {
    first: 'Priya',
    last: 'Nair',
    sex: 'F',
    age: 50,
    ckd: null,
    als: 'unknown',
    al: [],
    pmh: 'Referred for evaluation of persistently raised blood pressure and proteinuria on an outside urine test (report not available).',
    fh: '',
    sh: '',
    c: [],
    m: [],
    L: null,
    e: [],
  },
  {
    first: 'Aditya',
    last: 'Singh',
    sex: 'M',
    age: 61,
    ckd: 'G5',
    als: 'has',
    al: [['Latex', 'Contact dermatitis', 'mild']],
    pmh: 'Hypertensive and diabetic kidney disease. Pre-dialysis planning in progress.',
    fh: 'Brother has hypertension.',
    sh: 'Retired army officer. Former smoker.',
    c: [
      ['N18.5', 'Chronic kidney disease, stage 5', 'nephrology', 1, 6],
      [
        'I12.0',
        'Hypertensive CKD with stage 5 CKD or end-stage kidney disease',
        'nephrology',
        0,
        6,
      ],
      ['D63.1', 'Anemia in chronic kidney disease', 'comorbidity', 0, 3],
      ['N25.81', 'Secondary hyperparathyroidism of renal origin', 'comorbidity', 0, 2],
    ],
    m: [
      ['Furosemide', '80 mg', 'Oral', 'Twice daily', 400, null],
      ['Amlodipine', '10 mg', 'Oral', 'Once daily', 800, null],
      ['Calcium acetate', '667 mg', 'Oral', 'Three times daily with meals', 300, null],
      ['Sodium bicarbonate', '500 mg', 'Oral', 'Twice daily', 300, null],
    ],
    L: {
      n: 6,
      e0: 19,
      e1: 11,
      span: 400,
      last: 6,
      K: 5.9,
      Kl: 6.2,
      HB: 9.1,
      CA: 7.9,
      PHOS: 6.4,
      UACR: 900,
    },
    e: [
      [
        180,
        'follow_up',
        'Breathlessness and swelling',
        ['Breathlessness', 'Leg swelling', 'Nausea'],
        'BP 160/94. Bibasal crackles. Pitting edema to knees.',
        'CKD G5 with volume overload.',
        'Diuretic adjustment. Dialysis access planning.',
        [160, 94, 88, 36.6, 79],
        'final',
        30,
      ],
      [
        60,
        'follow_up',
        'Pre-dialysis counselling',
        ['Fatigue', 'Itching'],
        'BP 150/90. Mild edema.',
        'CKD G5, symptomatic uremia emerging.',
        'Discuss renal replacement options with family.',
        [150, 90, 84, 36.6, 77],
        'final',
        30,
      ],
      [
        6,
        'follow_up',
        'Review of results',
        ['Fatigue', 'Nausea', 'Muscle cramps'],
        'BP 148/88.',
        'Critically high potassium on latest result. eGFR 11.',
        'Same-week repeat potassium. Urgent dialysis planning discussion.',
        [148, 88, 86, 36.6, 76.5],
        'final',
        7,
      ],
    ],
  },
  {
    first: 'Kavita',
    last: 'Joshi',
    sex: 'F',
    age: 34,
    ckd: null,
    als: 'nka',
    al: [],
    pmh: 'Systemic lupus erythematosus with lupus nephritis class IV diagnosed 4 years ago.',
    fh: 'None documented.',
    sh: 'Graphic designer. Non-smoker.',
    c: [['M32.14', 'Glomerular disease in systemic lupus erythematosus', 'nephrology', 1, 4]],
    m: [
      ['Mycophenolate mofetil', '500 mg', 'Oral', 'Twice daily', 700, null],
      ['Prednisolone', '5 mg', 'Oral', 'Once daily', 700, null],
      ['Hydroxychloroquine', '200 mg', 'Oral', 'Twice daily', 900, 40],
    ],
    L: {
      n: 5,
      e0: 58,
      e1: 52,
      span: 500,
      last: 25,
      K: 4.2,
      HB: 11.5,
      CA: 9.0,
      PHOS: 3.9,
      UACR: 320,
    },
    e: [
      [
        150,
        'follow_up',
        'Joint pain and fatigue',
        ['Joint pain', 'Fatigue'],
        'BP 118/74. No rash.',
        'Lupus nephritis, partially responded. Moderate albuminuria.',
        'Continue immunosuppression. Repeat complement and UACR.',
        [118, 74, 78, 36.6, 60],
        'final',
        90,
      ],
      [
        24,
        'follow_up',
        'Review of labs',
        ['Fatigue'],
        'BP 120/76.',
        'Mildly reduced eGFR. Albuminuria persists.',
        'Continue plan. Discuss renal biopsy repeat if no improvement.',
        [120, 76, 76, 36.6, 59.5],
        'final',
        60,
      ],
    ],
  },
];

export const CLINICIANS = ['Dr. Anita Rao', 'Dr. Karan Malhotra'] as const;

export function seedDb(now: number = Date.now()): Db {
  const rnd = mulberry32(42);
  const db: Db = {
    patients: [],
    conditions: [],
    meds: [],
    allergies: [],
    encounters: [],
    labReports: [],
    labResults: [],
    aiSummaries: [],
    config: { toolsEnabled: true, maxToolIterations: 4, dailyQuota: 50 },
  };

  SPECS.forEach((s, i) => {
    // Order of rnd() calls is the same as the HTML, so the generated values match it exactly.
    const dob = new Date(new Date(now).getFullYear() - s.age, 3, 10 + Math.floor(rnd() * 60));
    const p = {
      id: uid(),
      mrn: 'PT-' + String(101 + i).padStart(6, '0'),
      first: s.first,
      last: s.last,
      dob: isoDate(dob),
      sex: s.sex,
      phone: '+91 98' + String(Math.floor(10000000 + rnd() * 89999999)),
      email: (s.first + '.' + s.last).toLowerCase() + '@example.test',
      address: '',
      pmh: s.pmh,
      fh: s.fh,
      sh: s.sh,
      allergyStatus: s.als,
      ckd: s.ckd,
      version: 1,
      deletedAt: null,
      createdAt: new Date(now - 400 * DAY).toISOString(),
    };
    db.patients.push(p);

    s.al.forEach((a) =>
      db.allergies.push({
        id: uid(),
        patientId: p.id,
        allergen: a[0],
        reaction: a[1],
        severity: a[2],
      }),
    );
    s.c.forEach((c) =>
      db.conditions.push({
        id: uid(),
        patientId: p.id,
        icd10: c[0],
        desc: c[1],
        category: c[2],
        isPrimary: !!c[3],
        status: 'active',
        onset: isoDate(now - c[4] * 365 * DAY),
        sourceEncounterId: null,
        deletedAt: null,
      }),
    );
    s.m.forEach((m) =>
      db.meds.push({
        id: uid(),
        patientId: p.id,
        name: m[0],
        dose: m[1],
        route: m[2],
        freq: m[3],
        start: isoDate(now - m[4] * DAY),
        end: m[5] != null ? isoDate(now - m[5] * DAY) : null,
        status: 'active',
      }),
    );
    s.e.forEach((e, j) => {
      const d = new Date(now - e[0] * DAY);
      d.setHours(10, 15, 0, 0);
      const first = s.c[0];
      db.encounters.push({
        id: uid(),
        patientId: p.id,
        date: d.toISOString(),
        type: e[1],
        clinician: CLINICIANS[(i + j) % 2] as string,
        cc: e[2],
        symptoms: e[3],
        exam: e[4],
        assessment: e[5],
        plan: e[6],
        followUp: e[9] ? isoDate(d.getTime() + e[9] * DAY) : '',
        status: e[8],
        vitals: e[7]
          ? { sys: e[7][0], dia: e[7][1], hr: e[7][2], temp: e[7][3], wt: e[7][4] }
          : null,
        diagnoses: e[5]
          ? [{ icd: first ? first[0] : '', desc: first ? first[1] : '', condId: null }]
          : [],
        version: 1,
        deletedAt: null,
      });
    });

    const L = s.L;
    if (L) {
      for (let k = 0; k < L.n; k++) {
        const f = L.n === 1 ? 1 : k / (L.n - 1);
        const ms = now - (L.last + L.span * (1 - f)) * DAY;
        const eg =
          k === 0
            ? L.e0
            : k === L.n - 1
              ? L.e1
              : Math.round(L.e0 + (L.e1 - L.e0) * f + (rnd() - 0.5) * 3);
        const age = (ms - dob.getTime()) / (365.25 * DAY);
        const scr = creatFromEgfr(eg, age, p.sex);
        const rep = {
          id: uid(),
          patientId: p.id,
          collectedAt: new Date(ms).toISOString(),
          labName: 'Metro Diagnostics Laboratory',
          notes: '',
          enteredBy: 'Dr. Anita Rao',
          createdAt: new Date(ms).toISOString(),
        };
        db.labReports.push(rep);
        const add = (t: keyof typeof LAB_TESTS, v: number, orig?: { v: number; u: string }) => {
          const r = rangeFor(t, p.sex);
          const o = orig ?? { v, u: LAB_TESTS[t].canon };
          db.labResults.push({
            id: uid(),
            reportId: rep.id,
            patientId: p.id,
            collectedAt: rep.collectedAt,
            test: t,
            value: v,
            unit: LAB_TESTS[t].canon,
            valueOriginal: o.v,
            unitOriginal: o.u,
            refLow: r.low,
            refHigh: r.high,
            flag: flagFor(v, r),
          });
        };
        const egRep = k === L.n - 1 && L.bump ? eg + L.bump : eg;
        add('CREAT', scr, L.conv === k ? { v: Math.round(scr / 0.0113), u: 'µmol/L' } : undefined);
        add('EGFR', egRep);
        add('BUN', Math.max(6, Math.round((10 + (scr - 0.9) * 14 + (rnd() - 0.5) * 3) * 10) / 10));
        const kv = k === L.n - 1 && L.Kl ? L.Kl : Math.round((L.K + (rnd() - 0.5) * 0.4) * 10) / 10;
        add('K', kv);
        add('HB', Math.round((L.HB + (rnd() - 0.5) * 0.6) * 10) / 10);
        add('CA', Math.round((L.CA + (rnd() - 0.5) * 0.4) * 10) / 10);
        add('PHOS', Math.round((L.PHOS + (rnd() - 0.5) * 0.5) * 10) / 10);
        if (k % 2 === 0 || k === L.n - 1) add('UACR', Math.round(L.UACR * (0.85 + rnd() * 0.3)));
      }
    }
  });
  return db;
}
