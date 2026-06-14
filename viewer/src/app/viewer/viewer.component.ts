import {
  Component, OnInit, OnDestroy, ElementRef, ViewChild, AfterViewInit
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { DicomWebService, DicomInstance, dicomStr } from '../core/dicomweb.service';
import { AiService, AiInferResult, MaskResult } from '../core/ai.service';

interface FrameInfo {
  instanceUID: string;
  frameNumber: number;
  imageUrl: string;
}

@Component({
  selector: 'app-viewer',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './viewer.component.html',
  styles: [`
    :host {
      display: flex;
      flex-direction: column;
      height: 100vh;
      background: #000;
      overflow: hidden;
    }

    .toolbar {
      display: flex;
      align-items: center;
      gap: 12px;
      background: #111827;
      padding: 8px 16px;
      border-bottom: 1px solid #1e293b;
      flex-shrink: 0;
      flex-wrap: wrap;
    }

    .toolbar .back-btn {
      background: transparent;
      border: 1px solid #334155;
      color: #94a3b8;
      border-radius: 4px;
      padding: 5px 12px;
      font-size: 0.82rem;
      cursor: pointer;
    }

    .toolbar .back-btn:hover { background: #1e293b; }

    .toolbar .series-info {
      color: #64748b;
      font-size: 0.8rem;
      margin-right: auto;
    }

    .toolbar .series-info strong { color: #90caf9; }

    .tool-group {
      display: flex;
      gap: 4px;
    }

    .tool-btn {
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      border-radius: 4px;
      padding: 5px 10px;
      font-size: 0.78rem;
      cursor: pointer;
      min-width: 60px;
    }

    .tool-btn.active {
      background: #1565c0;
      border-color: #1976d2;
      color: #fff;
    }

    .tool-btn:hover:not(.active) { background: #263850; }

    .ai-btn {
      background: #1b5e20;
      border: 1px solid #2e7d32;
      color: #a5d6a7;
      border-radius: 4px;
      padding: 5px 14px;
      font-size: 0.82rem;
      cursor: pointer;
      font-weight: 600;
    }

    .ai-btn:disabled {
      background: #1c2833;
      border-color: #2c3e50;
      color: #4a6270;
      cursor: not-allowed;
    }

    .ai-btn:hover:not(:disabled) { background: #2e7d32; }

    .ai-status {
      font-size: 0.78rem;
      padding: 3px 10px;
      border-radius: 10px;
    }

    .ai-status.pending  { background: #37474f; color: #90a4ae; }
    .ai-status.running  { background: #e65100; color: #ffe0b2; }
    .ai-status.done     { background: #1b5e20; color: #a5d6a7; }
    .ai-status.failed   { background: #b71c1c; color: #ffcdd2; }

    .viewport-area {
      flex: 1;
      position: relative;
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000;
    }

    canvas.dicom-canvas {
      display: block;
      max-width: 100%;
      max-height: 100%;
      cursor: crosshair;
      image-rendering: pixelated;
    }

    .overlay-canvas {
      position: absolute;
      top: 0;
      left: 0;
      pointer-events: none;
    }

    .hud {
      position: absolute;
      top: 8px;
      left: 8px;
      font-size: 0.72rem;
      color: #ffd54f;
      font-family: monospace;
      line-height: 1.6;
      pointer-events: none;
      text-shadow: 1px 1px 2px #000;
    }

    .hud-right {
      position: absolute;
      top: 8px;
      right: 8px;
      font-size: 0.72rem;
      color: #90caf9;
      font-family: monospace;
      line-height: 1.6;
      pointer-events: none;
      text-align: right;
      text-shadow: 1px 1px 2px #000;
    }

    .frame-counter {
      position: absolute;
      bottom: 12px;
      left: 50%;
      transform: translateX(-50%);
      font-size: 0.8rem;
      color: #ccc;
      background: rgba(0,0,0,0.5);
      padding: 4px 12px;
      border-radius: 12px;
      pointer-events: none;
    }

    .loading-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(0,0,0,0.7);
      color: #90caf9;
      font-size: 1rem;
    }

    .scrollbar-hint {
      position: absolute;
      right: 8px;
      bottom: 40px;
      font-size: 0.7rem;
      color: #475569;
      pointer-events: none;
    }

    .wl-display {
      font-size: 0.72rem;
      color: #ffd54f;
      font-family: monospace;
    }
  `]
})
export class ViewerComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('dicomCanvas') canvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('overlayCanvas') overlayRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('viewportArea') viewportAreaRef!: ElementRef<HTMLDivElement>;

  studyUID = '';
  seriesUID = '';

  frames: FrameInfo[] = [];
  currentFrameIndex = 0;
  loadingFrames = true;
  frameLoadError: string | null = null;

  // Window/Level state
  windowCenter = 40;
  windowWidth = 400;
  activeTool: 'wl' | 'pan' | 'zoom' = 'wl';

  // Pan/zoom state
  panX = 0;
  panY = 0;
  zoom = 1.0;

  // Mouse drag state
  private isDragging = false;
  private dragStartX = 0;
  private dragStartY = 0;
  private dragStartWC = 0;
  private dragStartWW = 0;
  private dragStartPanX = 0;
  private dragStartPanY = 0;
  private dragStartZoom = 1.0;

  // AI job state
  aiJobId: string | null = null;
  aiStatus: 'idle' | 'pending' | 'running' | 'done' | 'failed' = 'idle';
  aiResult: AiInferResult | null = null;
  private aiSub?: Subscription;

  // Image cache
  private imageCache = new Map<string, HTMLImageElement>();
  private currentImage: HTMLImageElement | null = null;
  private animFrameId: number | null = null;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private dicomWeb: DicomWebService,
    private aiService: AiService,
  ) {}

  ngOnInit(): void {
    this.studyUID = this.route.snapshot.paramMap.get('studyUID') ?? '';
    this.seriesUID = this.route.snapshot.paramMap.get('seriesUID') ?? '';
    this.loadInstances();
  }

  ngAfterViewInit(): void {
    this.setupMouseHandlers();
  }

  ngOnDestroy(): void {
    this.aiSub?.unsubscribe();
    if (this.animFrameId !== null) cancelAnimationFrame(this.animFrameId);
  }

  // ── Data loading ────────────────────────────────────────────────────────────

  loadInstances(): void {
    this.loadingFrames = true;

    if (this.studyUID.startsWith('demo-')) {
      this.frames = this.buildDemoFrames();
      this.loadingFrames = false;
      this.loadCurrentFrame();
      return;
    }

    this.dicomWeb.searchInstances(this.studyUID, this.seriesUID).subscribe({
      next: (instances) => {
        const sorted = instances.sort((a, b) => {
          const na = Number(dicomStr(a['00200013'])) || 0;
          const nb = Number(dicomStr(b['00200013'])) || 0;
          return na - nb;
        });

        // Pick window/level from the first instance's DICOM metadata if present
        if (sorted.length > 0) {
          const wc = Number(dicomStr((sorted[0] as any)['00281050']));
          const ww = Number(dicomStr((sorted[0] as any)['00281051']));
          if (wc && ww) {
            this.windowCenter = wc;
            this.windowWidth = ww;
          }
        }

        this.frames = sorted.map(inst => {
          const uid = dicomStr(inst['00080018']);
          return {
            instanceUID: uid,
            frameNumber: 1,
            imageUrl: this.dicomWeb.frameUrl(
              this.studyUID, this.seriesUID, uid, 1,
              this.windowCenter, this.windowWidth
            ),
          };
        });

        this.loadingFrames = false;
        if (this.frames.length > 0) this.loadCurrentFrame();
        else this.frameLoadError = 'No instances found in this series.';
      },
      error: (err) => {
        this.frameLoadError = `Failed to load series: ${err.message}`;
        this.loadingFrames = false;
        this.frames = this.buildDemoFrames();
        this.loadCurrentFrame();
      }
    });
  }

  private buildDemoFrames(): FrameInfo[] {
    // Demo: 20 synthetic frames — canvas draws a CT-like gradient
    return Array.from({ length: 20 }, (_, i) => ({
      instanceUID: `demo-instance-${i + 1}`,
      frameNumber: 1,
      imageUrl: '',  // handled by drawDemoFrame()
    }));
  }

  loadCurrentFrame(): void {
    const frame = this.frames[this.currentFrameIndex];
    if (!frame) return;

    if (!frame.imageUrl) {
      // Demo mode: render synthetic frame on canvas directly
      this.drawSyntheticFrame(this.currentFrameIndex);
      return;
    }

    const cached = this.imageCache.get(frame.imageUrl);
    if (cached) {
      this.currentImage = cached;
      this.renderFrame();
      this.prefetchAdjacent();
      return;
    }

    const img = new Image();
    img.onload = () => {
      this.imageCache.set(frame.imageUrl, img);
      this.currentImage = img;
      this.renderFrame();
      this.prefetchAdjacent();
    };
    img.onerror = () => {
      this.drawSyntheticFrame(this.currentFrameIndex);
    };
    img.src = this.buildFrameUrl(frame);
  }

  private buildFrameUrl(frame: FrameInfo): string {
    return this.dicomWeb.frameUrl(
      this.studyUID, this.seriesUID, frame.instanceUID, frame.frameNumber,
      this.windowCenter, this.windowWidth
    );
  }

  private prefetchAdjacent(): void {
    const neighbors = [-2, -1, 1, 2];
    for (const delta of neighbors) {
      const idx = this.currentFrameIndex + delta;
      if (idx < 0 || idx >= this.frames.length) continue;
      const f = this.frames[idx];
      if (!f.imageUrl || this.imageCache.has(f.imageUrl)) continue;
      const img = new Image();
      img.src = this.buildFrameUrl(f);
      img.onload = () => this.imageCache.set(f.imageUrl, img);
    }
  }

  // ── Canvas rendering ────────────────────────────────────────────────────────

  private renderFrame(): void {
    if (!this.canvasRef) return;
    const canvas = this.canvasRef.nativeElement;
    const ctx = canvas.getContext('2d');
    if (!ctx || !this.currentImage) return;

    const area = this.viewportAreaRef?.nativeElement;
    if (area) {
      canvas.width = area.clientWidth;
      canvas.height = area.clientHeight;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(canvas.width / 2 + this.panX, canvas.height / 2 + this.panY);
    ctx.scale(this.zoom, this.zoom);

    const img = this.currentImage;
    ctx.drawImage(img, -img.naturalWidth / 2, -img.naturalHeight / 2);
    ctx.restore();

    this.renderOverlay();
  }

  private drawSyntheticFrame(index: number): void {
    if (!this.canvasRef) return;
    const canvas = this.canvasRef.nativeElement;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const area = this.viewportAreaRef?.nativeElement;
    const w = area ? area.clientWidth : 512;
    const h = area ? area.clientHeight : 512;
    canvas.width = w;
    canvas.height = h;

    // Draw a synthetic CT-like circular anatomy
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, w, h);

    const cx = w / 2 + this.panX;
    const cy = h / 2 + this.panY;
    const r = Math.min(w, h) * 0.38 * this.zoom;

    // Soft tissue background
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, `rgba(80,80,80,${0.7 + index * 0.01})`);
    grad.addColorStop(0.6, 'rgba(40,40,40,0.9)');
    grad.addColorStop(1, 'rgba(0,0,0,1)');
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();

    // Lung fields
    const lungR = r * 0.28;
    [-0.35, 0.35].forEach(offset => {
      const lg = ctx.createRadialGradient(
        cx + r * offset, cy - r * 0.05, 0,
        cx + r * offset, cy - r * 0.05, lungR
      );
      lg.addColorStop(0, 'rgba(10,10,10,0.95)');
      lg.addColorStop(1, 'rgba(30,30,30,0.6)');
      ctx.beginPath();
      ctx.ellipse(cx + r * offset, cy - r * 0.05, lungR, lungR * 1.3, 0, 0, Math.PI * 2);
      ctx.fillStyle = lg;
      ctx.fill();
    });

    // Spine
    ctx.beginPath();
    ctx.arc(cx, cy + r * 0.55, r * 0.08, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(220,220,220,0.85)';
    ctx.fill();

    // Aorta
    ctx.beginPath();
    ctx.arc(cx - r * 0.1, cy + r * 0.2, r * 0.04, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(160,80,80,0.7)';
    ctx.fill();

    // Frame counter overlay
    ctx.fillStyle = 'rgba(255,213,79,0.8)';
    ctx.font = `${12 * this.zoom}px monospace`;
    ctx.fillText(`Frame ${index + 1} / ${this.frames.length}  [DEMO]`, cx - 70, cy - r - 10);

    this.renderOverlay();
  }

  private renderOverlay(): void {
    if (!this.overlayRef) return;
    const canvas = this.overlayRef.nativeElement;
    const mainCanvas = this.canvasRef?.nativeElement;
    if (!mainCanvas) return;

    canvas.width = mainCanvas.width;
    canvas.height = mainCanvas.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (this.aiStatus !== 'done' || !this.aiResult) return;

    const frame = this.frames[this.currentFrameIndex];
    if (!frame) return;

    const mask = this.aiResult.results.find(r => r.instance_uid === frame.instanceUID);
    if (!mask) return;

    // Transform from image space to canvas space
    const imgW = mask.cols;
    const imgH = mask.rows;
    const cw = canvas.width;
    const ch = canvas.height;

    const scale = Math.min(cw / imgW, ch / imgH) * this.zoom;
    const originX = cw / 2 + this.panX;
    const originY = ch / 2 + this.panY;

    const canvasCx = originX + (mask.mask.cx - imgW / 2) * scale;
    const canvasCy = originY + (mask.mask.cy - imgH / 2) * scale;
    const canvasR = mask.mask.r * scale;

    // Draw circle overlay
    ctx.beginPath();
    ctx.arc(canvasCx, canvasCy, canvasR, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(255, 82, 82, 0.9)';
    ctx.lineWidth = 2.5;
    ctx.stroke();

    // Fill with translucent red
    ctx.fillStyle = 'rgba(255, 82, 82, 0.15)';
    ctx.fill();

    // Label
    ctx.fillStyle = '#ff5252';
    ctx.font = 'bold 13px sans-serif';
    ctx.fillText(
      `${mask.mask.label} (${(mask.mask.confidence * 100).toFixed(0)}%)`,
      canvasCx - canvasR,
      canvasCy - canvasR - 6
    );
  }

  // ── Mouse interaction ───────────────────────────────────────────────────────

  private setupMouseHandlers(): void {
    const canvas = this.canvasRef?.nativeElement;
    if (!canvas) return;

    canvas.addEventListener('mousedown', (e: MouseEvent) => {
      this.isDragging = true;
      this.dragStartX = e.clientX;
      this.dragStartY = e.clientY;
      this.dragStartWC = this.windowCenter;
      this.dragStartWW = this.windowWidth;
      this.dragStartPanX = this.panX;
      this.dragStartPanY = this.panY;
      this.dragStartZoom = this.zoom;
      e.preventDefault();
    });

    canvas.addEventListener('mousemove', (e: MouseEvent) => {
      if (!this.isDragging) return;
      const dx = e.clientX - this.dragStartX;
      const dy = e.clientY - this.dragStartY;

      if (this.activeTool === 'wl') {
        // Right drag: window width; up drag: window center
        this.windowCenter = Math.round(this.dragStartWC - dy * 2);
        this.windowWidth = Math.max(1, Math.round(this.dragStartWW + dx * 4));
        this.invalidateWLCache();
        this.loadCurrentFrame();
      } else if (this.activeTool === 'pan') {
        this.panX = this.dragStartPanX + dx;
        this.panY = this.dragStartPanY + dy;
        this.redraw();
      } else if (this.activeTool === 'zoom') {
        this.zoom = Math.max(0.1, Math.min(10, this.dragStartZoom + dy * -0.01));
        this.redraw();
      }
    });

    canvas.addEventListener('mouseup', () => { this.isDragging = false; });
    canvas.addEventListener('mouseleave', () => { this.isDragging = false; });

    // Scroll to change frame
    canvas.addEventListener('wheel', (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 1 : -1;
      this.scrollFrame(delta);
    }, { passive: false });
  }

  scrollFrame(delta: number): void {
    const next = this.currentFrameIndex + delta;
    if (next < 0 || next >= this.frames.length) return;
    this.currentFrameIndex = next;
    this.loadCurrentFrame();
  }

  private invalidateWLCache(): void {
    // When W/L changes, clear cached images so they're re-fetched with new params
    this.imageCache.clear();
    this.currentImage = null;
    // Rebuild frame URLs with new W/L
    this.frames = this.frames.map(f => ({
      ...f,
      imageUrl: f.instanceUID.startsWith('demo-') ? '' :
        this.dicomWeb.frameUrl(
          this.studyUID, this.seriesUID, f.instanceUID, f.frameNumber,
          this.windowCenter, this.windowWidth
        ),
    }));
  }

  private redraw(): void {
    if (this.currentImage) {
      this.renderFrame();
    } else {
      this.drawSyntheticFrame(this.currentFrameIndex);
    }
  }

  setTool(tool: 'wl' | 'pan' | 'zoom'): void {
    this.activeTool = tool;
  }

  resetView(): void {
    this.panX = 0;
    this.panY = 0;
    this.zoom = 1.0;
    this.windowCenter = 40;
    this.windowWidth = 400;
    this.invalidateWLCache();
    this.loadCurrentFrame();
  }

  // ── AI inference ────────────────────────────────────────────────────────────

  runAiAnalysis(): void {
    if (this.aiStatus === 'pending' || this.aiStatus === 'running') return;

    const instanceUids = this.frames
      .slice(0, Math.min(5, this.frames.length))
      .map(f => f.instanceUID);

    this.aiStatus = 'pending';
    this.aiResult = null;
    this.renderOverlay();

    this.aiService.submitJob({
      studyUid: this.studyUID,
      seriesUid: this.seriesUID,
      instanceUids,
    }).subscribe({
      next: (job) => {
        this.aiJobId = job.id;
        this.aiStatus = 'running';
        this.pollAiJob(job.id);
      },
      error: (err) => {
        console.error('AI job submit failed:', err);
        this.aiStatus = 'failed';
        // Demo mode: simulate AI result
        this.simulateDemoAiResult(instanceUids);
      }
    });
  }

  private pollAiJob(jobId: string): void {
    this.aiSub?.unsubscribe();
    this.aiSub = this.aiService.pollUntilDone(jobId).subscribe({
      next: (status) => {
        if (status.status === 'DONE' && status.resultUrl) {
          this.aiService.getResult(status.resultUrl).subscribe({
            next: (result) => {
              this.aiResult = result;
              this.aiStatus = 'done';
              this.renderOverlay();
            },
            error: () => { this.aiStatus = 'failed'; }
          });
        } else if (status.status === 'FAILED') {
          this.aiStatus = 'failed';
        }
      },
      error: (err) => {
        console.error('AI poll error:', err);
        this.aiStatus = 'failed';
      }
    });
  }

  private simulateDemoAiResult(instanceUids: string[]): void {
    // Produce a local demo result when backend is not available
    setTimeout(() => {
      this.aiResult = {
        job_id: 'demo-job',
        study_uid: this.studyUID,
        series_uid: this.seriesUID,
        processing_time_ms: 312,
        results: instanceUids.map(uid => ({
          instance_uid: uid,
          rows: 512,
          cols: 512,
          mask: {
            cx: 256 + Math.floor(Math.random() * 30 - 15),
            cy: 256 + Math.floor(Math.random() * 30 - 15),
            r: 42,
            label: 'Nodule candidate',
            confidence: 0.87 + Math.random() * 0.08,
            type: 'circle',
          }
        }))
      };
      this.aiStatus = 'done';
      this.renderOverlay();
    }, 1500);
    this.aiStatus = 'running';
  }

  goBack(): void {
    this.router.navigate(['/']);
  }

  get frameLabel(): string {
    return `${this.currentFrameIndex + 1} / ${this.frames.length}`;
  }

  get wlLabel(): string {
    return `WC:${this.windowCenter}  WW:${this.windowWidth}`;
  }
}
