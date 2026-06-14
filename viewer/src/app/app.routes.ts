import { Routes } from '@angular/router';
import { WorklistComponent } from './worklist/worklist.component';
import { ViewerComponent } from './viewer/viewer.component';

export const routes: Routes = [
  { path: '', component: WorklistComponent },
  { path: 'viewer/:studyUID/:seriesUID', component: ViewerComponent },
  { path: '**', redirectTo: '' },
];
