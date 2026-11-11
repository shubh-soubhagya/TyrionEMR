import { Routes } from '@angular/router';
import { EmrAppShell } from '@layout/app-shell/app-shell';

// Route map from docs/ui-inventory.md section 8 (HLD 15.1). Every page is lazy-loaded; the shell
// is eager because it is the frame around all signed-in pages.
// Guards (authGuard / guestGuard) arrive with Phase 5.
const tab = (title: string) => ({ title });

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('@features/auth/login-page').then((m) => m.LoginPage),
  },
  {
    path: 'signup',
    loadComponent: () => import('@features/auth/signup-page').then((m) => m.SignupPage),
  },
  {
    path: '',
    component: EmrAppShell,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        loadComponent: () =>
          import('@features/dashboard/dashboard-page').then((m) => m.DashboardPage),
      },
      {
        path: 'patients',
        loadComponent: () =>
          import('@features/patients/patient-list-page').then((m) => m.PatientListPage),
      },
      {
        path: 'patients/:id',
        loadComponent: () =>
          import('@features/patients/patient-shell-page').then((m) => m.PatientShellPage),
        children: [
          { path: '', pathMatch: 'full', redirectTo: 'overview' },
          // Placeholders: each tab gets its own lazy component in its feature phase.
          { path: 'overview', ...placeholderTab(), data: tab('Overview') },
          { path: 'conditions', ...placeholderTab(), data: tab('Conditions') },
          { path: 'meds', ...placeholderTab(), data: tab('Medications and allergies') },
          { path: 'encounters', ...placeholderTab(), data: tab('Encounters') },
          { path: 'labs', ...placeholderTab(), data: tab('Labs') },
          { path: 'ai', ...placeholderTab(), data: tab('AI summary') },
        ],
      },
    ],
  },
  {
    path: '**',
    loadComponent: () => import('@features/not-found/not-found-page').then((m) => m.NotFoundPage),
  },
];

function placeholderTab() {
  return {
    loadComponent: () =>
      import('@features/patients/patient-tab-placeholder').then((m) => m.PatientTabPlaceholder),
  };
}
