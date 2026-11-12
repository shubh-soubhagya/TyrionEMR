import {
  ChangeDetectionStrategy,
  Component,
  Directive,
  HostListener,
  Injectable,
  inject,
  input,
  signal,
} from '@angular/core';

/** Hover tooltip (html `#tooltip`, `data-tip`): first line bold, then plain lines. */
@Injectable({ providedIn: 'root' })
export class TooltipService {
  readonly lines = signal<readonly string[]>([]);
  readonly visible = signal(false);
  readonly x = signal(0);
  readonly y = signal(0);

  show(lines: readonly string[], event: MouseEvent): void {
    this.lines.set(lines);
    this.visible.set(true);
    this.move(event);
  }

  move(event: MouseEvent): void {
    this.x.set(Math.min(event.clientX + 14, window.innerWidth - 270));
    this.y.set(event.clientY + 16);
  }

  hide(): void {
    this.visible.set(false);
  }
}

@Directive({ selector: '[emrTip]' })
export class EmrTip {
  private readonly tooltip = inject(TooltipService);
  readonly emrTip = input.required<readonly string[]>();

  @HostListener('mouseenter', ['$event']) onEnter(e: MouseEvent): void {
    this.tooltip.show(this.emrTip(), e);
  }
  @HostListener('mousemove', ['$event']) onMove(e: MouseEvent): void {
    this.tooltip.move(e);
  }
  @HostListener('mouseleave') onLeave(): void {
    this.tooltip.hide();
  }
}

@Component({
  selector: 'emr-tooltip',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div
    id="tooltip"
    role="tooltip"
    [class.show]="t.visible()"
    [style.left.px]="t.x()"
    [style.top.px]="t.y()"
  >
    @for (line of t.lines(); track $index) {
      @if ($first) {
        <b>{{ line }}</b>
      } @else {
        <br />{{ line }}
      }
    }
  </div>`,
})
export class EmrTooltip {
  protected readonly t = inject(TooltipService);
}
