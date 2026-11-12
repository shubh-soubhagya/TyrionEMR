import { Routes } from '@angular/router';
import { environment } from '@env/environment';
import { EmrAppShell } from '@layout/app-shell/app-shell';

// Route map from docs/ui-inventory.md section 8 (HLD 15.1). Every page is lazy-loaded; the shell
// is eager because it is the frame around all signed-in pages.
// Guards (authGuard / guestGuard) arrive with Phase 5.

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
      // Dev-only component catalogue: not registered in production builds.
      ...(environment.production
        ? []
        : [
            {
              path: 'dev/ui-kit',
              loadComponent: () => import('@features/dev/ui-kit-page').then((m) => m.UiKitPage),
            },
          ]),
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
          {
            path: 'overview',
            loadComponent: () => import('@features/patients/tabs/overview-tab').then((m) => m.OverviewTab),
          },
          {
            path: 'conditions',
            loadComponent: () => import('@features/patients/tabs/conditions-tab').then((m) => m.ConditionsTab),
          },
          {
            path: 'meds',
            loadComponent: () => import('@features/patients/tabs/meds-tab').then((m) => m.MedsTab),
          },
          {
            path: 'encounters',
            loadComponent: () => import('@features/patients/tabs/encounters-tab').then((m) => m.EncountersTab),
          },
          {
            path: 'labs',
            loadComponent: () => import('@features/patients/tabs/labs-tab').then((m) => m.LabsTab),
          },
          {
            path: 'ai',
            loadComponent: () => import('@features/patients/tabs/ai-tab').then((m) => m.AiTab),
          },
        ],
      },
    ],
  },
  {
    path: '**',
    loadComponent: () => import('@features/not-found/not-found-page').then((m) => m.NotFoundPage),
  },
];

