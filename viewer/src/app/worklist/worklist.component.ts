import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { DicomWebService, DicomStudy, dicomStr } from '../core/dicomweb.service';

interface StudyRow {
  studyUID: string;
  patientName: string;
  patientID: string;
  studyDate: string;
  studyDescription: string;
  modalities: string;
  seriesUID?: string; // populated after series fetch
}

@Component({
  selector: 'app-worklist',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './worklist.component.html',
  styles: [`
    .worklist-container {
      padding: 0;
      min-height: 100vh;
      background: #0d0d0d;
    }

    .header {
      background: linear-gradient(135deg, #0a1628 0%, #1a237e 100%);
      padding: 20px 24px;
      display: flex;
      align-items: center;
      gap: 16px;
      border-bottom: 1px solid #1e3a5f;
    }

    .logo {
      font-size: 1.4rem;
      font-weight: 700;
      color: #90caf9;
      letter-spacing: 0.1em;
    }

    .logo span {
      color: #42a5f5;
    }

    .header h1 {
      font-size: 1rem;
      font-weight: 400;
      color: #78909c;
    }

    .search-bar {
      background: #111827;
      padding: 12px 24px;
      display: flex;
      gap: 12px;
      align-items: center;
      border-bottom: 1px solid #1e293b;
    }

    .search-bar input {
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 4px;
      padding: 6px 12px;
      color: #e2e8f0;
      font-size: 0.875rem;
      width: 220px;
    }

    .search-bar input:focus {
      outline: none;
      border-color: #42a5f5;
    }

    .search-bar label {
      font-size: 0.8rem;
      color: #64748b;
    }

    .refresh-btn {
      margin-left: auto;
      background: #1e3a5f;
      color: #90caf9;
      border: 1px solid #1e4976;
      border-radius: 4px;
      padding: 6px 14px;
      font-size: 0.85rem;
      cursor: pointer;
    }

    .refresh-btn:hover { background: #1e4976; }

    .table-container {
      overflow-x: auto;
    }

    .loading, .empty, .error-msg {
      padding: 60px;
      text-align: center;
      color: #64748b;
      font-size: 1rem;
    }

    .error-msg { color: #ef5350; }

    .modality-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 0.72rem;
      font-weight: 700;
      margin: 1px;
      background: #1e3a5f;
      color: #90caf9;
    }

    .study-date {
      font-variant-numeric: tabular-nums;
      color: #94a3b8;
    }

    .patient-name {
      font-weight: 600;
      color: #e2e8f0;
    }

    .patient-id {
      font-size: 0.78rem;
      color: #64748b;
    }

    .count-badge {
      font-size: 0.75rem;
      color: #64748b;
    }

    tr.clickable:hover td {
      background: #1e293b;
      cursor: pointer;
    }
  `]
})
export class WorklistComponent implements OnInit {
  studies: StudyRow[] = [];
  filteredStudies: StudyRow[] = [];
  loading = true;
  error: string | null = null;

  patientFilter = '';
  dateFilter = '';
  modalityFilter = '';

  constructor(
    private dicomWeb: DicomWebService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.loadStudies();
  }

  loadStudies(): void {
    this.loading = true;
    this.error = null;

    this.dicomWeb.searchStudies().subscribe({
      next: (raw) => {
        this.studies = raw.map(s => this.mapStudy(s));
        this.applyFilter();
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load worklist: ${err.message ?? 'Unknown error'}. Is the imaging-api running?`;
        this.loading = false;
        // Show demo data so the UI is still useful without a backend
        this.studies = DEMO_STUDIES;
        this.filteredStudies = DEMO_STUDIES;
      }
    });
  }

  applyFilter(): void {
    this.filteredStudies = this.studies.filter(s => {
      const nameMatch = !this.patientFilter ||
        s.patientName.toLowerCase().includes(this.patientFilter.toLowerCase());
      const dateMatch = !this.dateFilter || s.studyDate.includes(this.dateFilter);
      const modMatch = !this.modalityFilter ||
        s.modalities.toLowerCase().includes(this.modalityFilter.toLowerCase());
      return nameMatch && dateMatch && modMatch;
    });
  }

  openViewer(study: StudyRow): void {
    // Fetch first series UID then navigate
    if (study.seriesUID) {
      this.router.navigate(['/viewer', study.studyUID, study.seriesUID]);
      return;
    }
    this.dicomWeb.searchSeries(study.studyUID).subscribe({
      next: (series) => {
        const firstSeriesUID = series.length > 0 ? dicomStr(series[0]['0020000E']) : 'unknown';
        study.seriesUID = firstSeriesUID;
        this.router.navigate(['/viewer', study.studyUID, firstSeriesUID]);
      },
      error: () => {
        // Navigate anyway with a placeholder — demo data
        this.router.navigate(['/viewer', study.studyUID, 'demo-series']);
      }
    });
  }

  formatDate(raw: string): string {
    if (!raw || raw.length !== 8) return raw;
    return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  }

  getModalityBadges(modalities: string): string[] {
    return modalities.split('\\').map(m => m.trim()).filter(m => m.length > 0);
  }

  private mapStudy(s: DicomStudy): StudyRow {
    const modAttr = s['00080061'];
    let modalities = '';
    if (modAttr?.Value) {
      modalities = modAttr.Value.map(v => String(v)).join('\\');
    }
    return {
      studyUID: dicomStr(s['0020000D']),
      patientName: dicomStr(s['00100010']) || 'Unknown',
      patientID: dicomStr(s['00100020']) || '',
      studyDate: this.formatDate(dicomStr(s['00080020'])),
      studyDescription: dicomStr(s['00081030']) || '—',
      modalities,
    };
  }
}

// Demo studies shown when the backend is unavailable
const DEMO_STUDIES: StudyRow[] = [
  {
    studyUID: 'demo-study-001',
    patientName: 'SMITH^JOHN',
    patientID: 'P001',
    studyDate: '2024-03-15',
    studyDescription: 'CT Chest w/o Contrast',
    modalities: 'CT',
    seriesUID: 'demo-series-001',
  },
  {
    studyUID: 'demo-study-002',
    patientName: 'DOE^JANE',
    patientID: 'P002',
    studyDate: '2024-03-20',
    studyDescription: 'MR Brain w/ and w/o',
    modalities: 'MR',
    seriesUID: 'demo-series-002',
  },
  {
    studyUID: 'demo-study-003',
    patientName: 'JOHNSON^ROBERT',
    patientID: 'P003',
    studyDate: '2024-04-01',
    studyDescription: 'CT Abdomen/Pelvis',
    modalities: 'CT',
    seriesUID: 'demo-series-003',
  },
  {
    studyUID: 'demo-study-004',
    patientName: 'WILLIAMS^MARY',
    patientID: 'P004',
    studyDate: '2024-04-10',
    studyDescription: 'PET CT Whole Body',
    modalities: 'PT\\CT',
    seriesUID: 'demo-series-004',
  },
];
