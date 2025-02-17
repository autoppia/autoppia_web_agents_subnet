import {Component, OnDestroy, OnInit} from '@angular/core';
import {Subject} from 'rxjs';
import {fuseAnimations} from '@fuse/animations';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {FuseConfirmDialogComponent} from '@fuse/components/confirm-dialog/confirm-dialog.component';
import {DepartmentRepository} from '../repositories/department.repository';

@Component({
    selector: 'list-department',
    templateUrl: './list-department.component.html',
    styleUrls: ['./list-department.component.scss'],
    animations: fuseAnimations
})
export class ListDepartmentComponent implements OnInit, OnDestroy {
    rows: any[] = []; // Initialize as an empty array
    loadingIndicator: boolean;
    reorderable: boolean;
    confirmDialogRef: MatDialogRef<FuseConfirmDialogComponent>;

    // Private
    private _unsubscribeAll: Subject<any>;

    /**
     * Constructor
     *
     * @param _departmentRepository
     * @param _matDialog
     * @param _matSnackBar
     */
    constructor(
        private _departmentRepository: DepartmentRepository,
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
        this.getListDepartment();
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
     * Fetch the list of departments
     */
    async getListDepartment(): Promise<void> {
        try {
            const response = await this._departmentRepository.getDepartment().toPromise();

            // Extract the `results` array from the response
            const departments = response?.results || [];

            // Process the data
            this.rows = departments.map(item => {
                return {
                    id: item.id,
                    name: item.name,
                    location: item.location,
                    isActive: item.isActive,
                    code: item.code
                };
            });

            this.loadingIndicator = false; // Hide loading indicator
        } catch (error) {
            console.error('Error fetching department data:', error);
            this.rows = []; // Fallback to an empty array
            this._matSnackBar.open('Error loading department data', 'OK', {
                verticalPosition: 'top',
                duration: 3000,
            });
            this.loadingIndicator = false; // Hide loading indicator
        }
    }

    /**
     * Delete a department by ID
     *
     * @param id
     */
    deleteDepartment(id: number): void {
        this.confirmDialogRef = this._matDialog.open(FuseConfirmDialogComponent, {
            disableClose: false
        });

        this.confirmDialogRef.componentInstance.confirmMessage = 'Are you sure you want to delete this record?';

        this.confirmDialogRef.afterClosed().subscribe(async (result) => {
            if (result) {
                try {
                    // Attempt to delete the department
                    await this._departmentRepository.deleteDepartmentById(id).toPromise();

                    // Treat 404 as a successful deletion
                    this._matSnackBar.open('Department deleted successfully', 'OK', {
                        verticalPosition: 'top',
                        duration: 3000
                    });

                    // Refresh the list after deletion
                    this.getListDepartment();
                } catch (error) {
                    console.error('Error deleting department:', error);

                    if (error.status === 404) {
                        // Treat 404 as a successful deletion
                        this._matSnackBar.open('Department deleted successfully', 'OK', {
                            verticalPosition: 'top',
                            duration: 3000
                        });

                        // Refresh the list after deletion
                        this.getListDepartment();
                    } else {
                        // Handle other errors
                        this._matSnackBar.open('Error deleting department', 'OK', {
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
     * Update a department by ID
     *
     * @param id
     */
    async updateDepartment(id: number): Promise<void> {
        this.loadingIndicator = true; // Show loading indicator

        try {
            this.rows = await this._departmentRepository.getDepartmentById(id).toPromise();
            this.loadingIndicator = false;
        } catch (err) {
            this.loadingIndicator = false;
            throw new Error('Error: ' + err);
        }
    }
}