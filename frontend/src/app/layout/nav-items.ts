import { IconName } from '@shared/ui/icon/icons';

export interface NavItem {
  /** Absolute router path. `routerLinkActive` also matches child paths (e.g. /patients/:id). */
  readonly path: string;
  readonly label: string;
  readonly icon: IconName;
}

// Same two items as the HTML sidebar (html:668, HLD 15.1: "Sidebar items: Dashboard, Patients").
export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/dashboard', label: 'Dashboard', icon: 'activity' },
  { path: '/patients', label: 'Patients', icon: 'users' },
];
