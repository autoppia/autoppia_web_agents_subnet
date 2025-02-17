import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatRippleModule } from '@angular/material/core';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorModule } from '@angular/material/paginator';
import { MatSelectModule } from '@angular/material/select';
import { MatRadioModule } from '@angular/material/radio';
import { MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSortModule } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { MatTabsModule } from '@angular/material/tabs';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { NgxChartsModule } from '@swimlane/ngx-charts';
import { AgmCoreModule } from '@agm/core';
import { NgxDatatableModule } from '@swimlane/ngx-datatable';
import { FuseSharedModule } from '@fuse/shared.module';
import { MatDialogModule } from '@angular/material/dialog';
import { FuseConfirmDialogModule } from '@fuse/components';

import { DepartmentRepository } from './repositories/department.repository';
import { FormDepartmentComponent } from './form/form-department.component';
import { FormDepartmentService } from './form/form-department.service';
import { ListDepartmentComponent } from './list/list-department.component';
import { MatCheckboxModule } from '@angular/material/checkbox';

const routes: Routes = [
    {
        path: 'department',
        component: FormDepartmentComponent,
        resolve  : {
            data: FormDepartmentService
        }
    },
    {
        path     : 'department/:id',
        component: FormDepartmentComponent,
        resolve  : {
            data: FormDepartmentService
        }
    },
    {
        path: 'list-department',
        component: ListDepartmentComponent
    }
];

@NgModule({
    declarations: [
        FormDepartmentComponent,
        ListDepartmentComponent,
    ],
    imports: [
        RouterModule.forChild(routes),
        MatButtonModule,
        MatFormFieldModule,
        MatIconModule,
        MatInputModule,
        MatSelectModule,
        MatRadioModule,
        MatChipsModule,
        MatDatepickerModule,
        FuseSharedModule,
        MatRippleModule,
        MatExpansionModule,
        MatPaginatorModule,
        MatSnackBarModule,
        MatSortModule,
        MatTableModule,
        MatTabsModule,
        NgxChartsModule,
        AgmCoreModule,
        MatCheckboxModule,
        NgxDatatableModule,
        MatDialogModule,
        FuseConfirmDialogModule,
    ],
    providers: [
        FormDepartmentService,
        DepartmentRepository,
    ]
})
export class DepartmentModule {
}
