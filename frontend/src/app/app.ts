import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { EmrToastContainer } from '@shared/ui/toast/toast-container';

@Component({
  selector: 'emr-root',
  imports: [RouterOutlet, EmrToastContainer],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <router-outlet />
    <emr-toast-container />
  `,
})
export class App {}
