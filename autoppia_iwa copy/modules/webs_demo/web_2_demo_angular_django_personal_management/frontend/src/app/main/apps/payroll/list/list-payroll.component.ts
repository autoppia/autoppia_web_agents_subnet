import {Component, OnDestroy, OnInit} from '@angular/core';
import {Subject} from 'rxjs';
import {fuseAnimations} from '@fuse/animations';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {FuseConfirmDialogComponent} from '@fuse/components/confirm-dialog/confirm-dialog.component';
import {PayrollRepository} from '../repositories/payroll.repository';
import {EmployeeRepository} from '../../employee/repositories/employee.repository';

@Component({
    selector: 'list-payroll',
    templateUrl: './list-payroll.component.html',
    styleUrls: ['./list-payroll.component.scss'],
    animations: fuseAnimations
})
export class ListPayrollComponent implements OnInit, OnDestroy {
    rows: any[] = [];
    loadingIndicator: boolean;
    reorderable: boolean;
    confirmDialogRef: MatDialogRef<FuseConfirmDialogComponent>;

    // Private
    private _unsubscribeAll: Subject<any>;

    /**
     * Constructor
     *
     * @param _payrollRepository
     * @param _employeeRepository
     * @param _matDialog
     * @param _matSnackBar
     */
    constructor(
        private _payrollRepository: PayrollRepository,
        private _employeeRepository: EmployeeRepository,
        private _matDialog: MatDialog,
        private _matSnackBar: MatSnackBar
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
        this.getListPayroll();
    }

    /**
     * On destroy
     */
    ngOnDestroy(): void {
        // Unsubscribe from all subscriptions
        this._unsubscribeAll.next();
        this._unsubscribeAll.complete();
    }

    // -----------------------------------------------------------------------------------------------------
    // @ Public methods
    // -----------------------------------------------------------------------------------------------------

    /**
     * Fetch the list of payroll records
     */
    async getListPayroll(): Promise<void> {
        try {
            const [payrollData, employeeData] = await Promise.all([
                this._payrollRepository.getPayroll().toPromise(),
                this._employeeRepository.getEmployee().toPromise()
            ]);

            // Extract the `results` array from the payrollData object
            const payrollResults = payrollData?.results || [];
            const employeeResults = employeeData?.results || [];

            // Process the data
            this.rows = payrollResults.map(payroll => {
                const employee = employeeResults.find(emp => emp.id === payroll.employee_id);
                return {
                    ...payroll,
                    employee: employee ? `${employee.firstName} ${employee.lastName}` : 'Unknown Employee'
                };
            });

            this.loadingIndicator = false; // Hide loading indicator
        } catch (error) {
            console.error('Error fetching payroll data:', error);
            this.rows = []; // Fallback to an empty array
            this._matSnackBar.open('Error loading payroll data', 'OK', {
                verticalPosition: 'top',
                duration: 3000,
            });
            this.loadingIndicator = false; // Hide loading indicator
        }
    }

    /**
     * Delete a payroll record by ID
     *
     * @param id
     */
    deletePayroll(id: number): void {
        this.confirmDialogRef = this._matDialog.open(FuseConfirmDialogComponent, {
            disableClose: false
        });

        this.confirmDialogRef.componentInstance.confirmMessage = 'Are you sure you want to delete this record?';

        this.confirmDialogRef.afterClosed().subscribe(async (result) => {
            if (result) {
                try {
                    // Attempt to delete the payroll record
                    const responseData = await this._payrollRepository.deletePayrollById(id).toPromise();

                    if (responseData?.response === 'OK' || responseData?.affected) {
                        this._matSnackBar.open('Payroll record deleted successfully', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });

                        // Refresh the list after deletion
                        this.getListPayroll();
                    } else {
                        this._matSnackBar.open('Verify if the record was already deleted or depends on another', 'ERROR', {
                            verticalPosition: 'top',
                            duration: 3000
                        });
                    }
                } catch (error) {
                    console.error('Error deleting payroll record:', error);

                    if (error.status === 404) {
                        // Treat 404 as a successful deletion
                        this._matSnackBar.open('Payroll record deleted successfully', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });

                        // Refresh the list after deletion
                        this.getListPayroll();
                    } else {
                        // Handle other errors
                        this._matSnackBar.open('Error deleting payroll record', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });
                    }
                } finally {
                    this.confirmDialogRef = null;
                }
            }
        });
    }

    /**
     * Update a payroll record by ID
     *
     * @param id
     */
    async updatePayroll(id: number): Promise<void> {
        this.loadingIndicator = true; // Show loading indicator

        try {
            this.rows = await this._payrollRepository.getPayrollById(id).toPromise();
            this.loadingIndicator = false;
        } catch (err) {
            this.loadingIndicator = false;
            throw new Error('Error: ' + err);
        }
    }
}