import {Component, OnDestroy, OnInit} from '@angular/core';
import {Subject} from 'rxjs';
import {fuseAnimations} from '@fuse/animations';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {FuseConfirmDialogComponent} from '@fuse/components/confirm-dialog/confirm-dialog.component';
import {AttendanceRepository} from '../repositories/attendance.repository';
import {EmployeeRepository} from '../../employee/repositories/employee.repository';

@Component({
    selector: 'list-attendance',
    templateUrl: './list-attendance.component.html',
    styleUrls: ['./list-attendance.component.scss'],
    animations: fuseAnimations
})
export class ListAttendanceComponent implements OnInit, OnDestroy {
    rows: any[] = []; // Initialize as an empty array
    loadingIndicator: boolean;
    reorderable: boolean;
    confirmDialogRef: MatDialogRef<FuseConfirmDialogComponent>;

    // Private
    private _unsubscribeAll: Subject<any>;

    /**
     * Constructor
     *
     * @param _attendanceRepository
     * @param _employeeRepository
     * @param _matDialog
     * @param _matSnackBar
     */
    constructor(
        private _attendanceRepository: AttendanceRepository,
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
        this.getListAttendance();
    }

    /**
     * On destroy
     */
    ngOnDestroy(): void {
        // Unsubscribe from all subscriptions
        this._unsubscribeAll.next();
        this._unsubscribeAll.complete();
    }

    /**
     * Fetch the list of attendance records
     */
    async getListAttendance(): Promise<void> {
        try {
            const [attendanceData, employeeData] = await Promise.all([
                this._attendanceRepository.getAttendance().toPromise(),
                this._employeeRepository.getEmployee().toPromise()
            ]);

            console.log('API Response - Attendance:', attendanceData); // Log the response
            console.log('API Response - Employee:', employeeData); // Log the response

            // Extract the `results` array from the attendanceData object
            const attendanceResults = attendanceData?.results || [];
            const employeeResults = employeeData?.results || [];

            // Process the data
            this.rows = attendanceResults.map(attendance => {
                const employee = employeeResults.find(emp => emp.id === attendance.employee_id);
                return {
                    ...attendance,
                    employee: employee ? `${employee.firstName} ${employee.lastName}` : 'Unknown Employee'
                };
            });

            this.loadingIndicator = false; // Hide loading indicator
        } catch (error) {
            console.error('Error fetching attendance data:', error);
            this.rows = []; // Fallback to an empty array
            this._matSnackBar.open('Error loading attendance data', 'OK', {
                verticalPosition: 'top',
                duration: 3000,
            });
            this.loadingIndicator = false; // Hide loading indicator
        }
    }

    /**
     * Delete an attendance record by ID
     *
     * @param id
     */
    deleteAttendance(id: number): void {
        this.confirmDialogRef = this._matDialog.open(FuseConfirmDialogComponent, {
            disableClose: false
        });

        this.confirmDialogRef.componentInstance.confirmMessage = 'Are you sure you want to delete this record?';

        this.confirmDialogRef.afterClosed().subscribe(async (result) => {
            if (result) {
                try {
                    // Attempt to delete the attendance record
                    const responseData = await this._attendanceRepository.deleteAttendanceById(id).toPromise();

                    if (responseData?.response === 'OK' || responseData?.affected) {
                        this._matSnackBar.open('Attendance record deleted successfully', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });

                        // Refresh the list after deletion
                        this.getListAttendance();
                    } else {
                        this._matSnackBar.open('Verify if the record was already deleted or depends on another', 'ERROR', {
                            verticalPosition: 'top',
                            duration: 3000
                        });
                    }
                } catch (error) {
                    console.error('Error deleting attendance record:', error);

                    if (error.status === 404) {
                        // Treat 404 as a successful deletion
                        this._matSnackBar.open('Attendance record deleted successfully', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });

                        // Refresh the list after deletion
                        this.getListAttendance();
                    } else {
                        // Handle other errors
                        this._matSnackBar.open('Error deleting attendance record', 'OK', {
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
     * Update an attendance record by ID
     *
     * @param id
     */
    async updateAttendance(id: number): Promise<void> {
        this.loadingIndicator = true; // Show loading indicator

        try {
            this.rows = await this._attendanceRepository.getAttendanceById(id).toPromise();
            this.loadingIndicator = false;
        } catch (err) {
            this.loadingIndicator = false;
            throw new Error('Error: ' + err);
        }
    }
}