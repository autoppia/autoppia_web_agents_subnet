import {Component, OnDestroy, OnInit} from '@angular/core';
import {Observable, Subject} from 'rxjs';
import {fuseAnimations} from '@fuse/animations';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {FuseConfirmDialogComponent} from '@fuse/components/confirm-dialog/confirm-dialog.component';
import {EmployeeRepository} from '../repositories/employee.repository';

@Component({
    selector: 'list-employee',
    templateUrl: './list-employee.component.html',
    styleUrls: ['./list-employee.component.scss'],
    animations: fuseAnimations
})
export class ListEmployeeComponent implements OnInit, OnDestroy {
    rows: object;
    loadingIndicator: boolean;
    reorderable: boolean;
    confirmDialogRef: MatDialogRef<FuseConfirmDialogComponent>;

    // Private
    private _unsubscribeAll: Subject<any>;

    /**
     * Constructor
     *
     * @param _employeeRepository
     * @param _matDialog
     * @param _matSnackBar
     */
    constructor(
        private _employeeRepository: EmployeeRepository,
        private _matDialog: MatDialog,
        private _matSnackBar: MatSnackBar,
    ) {
        // Set the defaults
        this.loadingIndicator = true;
        this.reorderable = true;

        // Set the private defaults
        this._unsubscribeAll = new Subject();
    }

    // -----------------------------------------------------------------------------------------------------
    // @ Lifecycle hooks
    // -----------------------------------------------------------------------------------------------------

    /**
     * On init
     */
     ngOnInit(): void {
        this.getListEmployee();
        this.loadingIndicator = false;
    }

    /**
     * On destroy
     */
    ngOnDestroy(): void {
        // Unsubscribe from all subscriptions
        this._unsubscribeAll.next();
        this._unsubscribeAll.complete();
    }

    async getListEmployee(): Promise<any> {

        try {
            this.rows = await this._employeeRepository.getEmployee().toPromise();
        } catch (error) {
            throw new Error('Error: ' + error);
        }
    }

    deleteEmployee(id): void {

        try {
            this.confirmDialogRef = this._matDialog.open(FuseConfirmDialogComponent, {
                disableClose: false
            });

            this.confirmDialogRef.componentInstance.confirmMessage = '¿Seguro quieres eliminar el registro?';

            this.confirmDialogRef.afterClosed().subscribe(async result => {
                if (result) {
                    const responseData = await this._employeeRepository.deleteEmployeeById(id).toPromise();
                    if (responseData?.response === 'OK' || responseData?.affected) {

                        setTimeout(() => {
                            this.getListEmployee();
                        }, 200);

                        this.loadingIndicator = false;

                        this._matSnackBar.open('El dato fue eliminado satisfactoriamente', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });

                    } else {
                        this._matSnackBar.open('Verificar si el dato ya habia sido eliminado o depende de otro', 'ERROR', {
                            verticalPosition: 'top',
                            duration: 3000
                        });
                    }

                }
                this.confirmDialogRef = null;
            });

        } catch (error) {
            Promise.reject(error);
        }

    }

    async updateEmployee(id): Promise<any> {
        try {
            this.rows = await this._employeeRepository.getEmployeeById(id).toPromise();
            this.loadingIndicator = false;
        } catch (err) {
            this.loadingIndicator = false;
            throw new Error('Error: ' + err);
        }
    }
}
