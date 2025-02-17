import {Component, OnDestroy, OnInit} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject} from 'rxjs';
import {takeUntil} from 'rxjs/operators';
import {fuseAnimations} from '@fuse/animations';
import {AttendanceRepository} from '../repositories/attendance.repository';
import {FormAttendanceService} from './form-attendance.service';
import {ActivatedRoute, Router} from '@angular/router';
import {EmployeeRepository} from '../../employee/repositories/employee.repository';
import {formatDate} from '@angular/common';

@Component({
    selector: 'forms-attendance',
    templateUrl: './form-attendance.component.html',
    styleUrls: ['./form-attendance.component.scss'],
    animations: fuseAnimations
})
export class FormAttendanceComponent implements OnInit, OnDestroy {

    id: number;
    routeParams: any;
    formAttendance: FormGroup;

    // Horizontal Stepper
    horizontalStepperStep1: FormGroup;
    horizontalStepperStep2: FormGroup;
    horizontalStepperStep3: FormGroup;

    // Vertical Stepper
    verticalStepperStep1: FormGroup;
    verticalStepperStep2: FormGroup;
    verticalStepperStep3: FormGroup;
    dataEmployeeSelect: any[] = []; // Initialize as an empty array

    // Private
    private _unsubscribeAll: Subject<any>;
    private attendance: any;
    private pageType: string;

    /**
     * Constructor
     *
     * @param {FormBuilder} _formBuilder
     * @param _attendanceRepository
     * @param _formAttendanceService
     * @param _matSnackBar
     * @param _router
     * @param _activatedRoute
     * @param _employeeRepository
     */
    constructor(
        private _formBuilder: FormBuilder,
        private _attendanceRepository: AttendanceRepository,
        private _formAttendanceService: FormAttendanceService,
        private _matSnackBar: MatSnackBar,
        private _router: Router,
        private _activatedRoute: ActivatedRoute,
        private _employeeRepository: EmployeeRepository,
    ) {
        // Set the private defaults
        this._unsubscribeAll = new Subject();

        this._activatedRoute
            .params
            .pipe(takeUntil(this._unsubscribeAll))
            .subscribe(params => {
                if (params?.id) {
                    this.id = +params?.id;
                    this.loadModel();
                }
            });
    }

    // -----------------------------------------------------------------------------------------------------
    // @ Lifecycle hooks
    // -----------------------------------------------------------------------------------------------------

    /**
     * On init
     */
    async ngOnInit() {

        // Initialize the form
        this.formAttendance = this.createAttendanceForm();

        // Subscribe to update attendance on changes
        this._formAttendanceService.onAttendanceChanged
            .pipe(takeUntil(this._unsubscribeAll))
            .subscribe(attendance => {
                if (attendance.id) {
                    this.attendance = attendance;
                    this.pageType = 'edit';
                } else {
                    this.pageType = 'new';
                    this.attendance = false;
                }

                this.formAttendance.patchValue(this.attendance);
            });

        // Fetch the list of employees
        await this.getEmployeeList();
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
     * Create attendance form
     *
     * @returns {FormGroup}
     */
    createAttendanceForm(): FormGroup {
        return this._formBuilder.group({
            id: [this.attendance?.id || null],
            employee_id: [this.attendance?.employee_id || null, [Validators.required]],
            date: [this.attendance?.date || null, [Validators.required]],
            status: [this.attendance?.status || null, [Validators.required]],
        });
    }

    /**
     * Load the attendance model
     */
    async loadModel(): Promise<void> {
        const response = await this._attendanceRepository.getAttendanceById(this.id).toPromise();
        this.formAttendance.patchValue(response);
    }

    /**
     * Fetch the list of employees
     */
    async getEmployeeList(): Promise<void> {
        try {
            const response = await this._employeeRepository.getEmployee().toPromise();

            // Ensure the response is an array
            if (Array.isArray(response.results)) {
                this.dataEmployeeSelect = response.results; // Assign the response directly
            } else {
                console.error('Expected an array but got:', response);
                this.dataEmployeeSelect = []; // Fallback to an empty array
            }

        } catch (error) {
            console.error('Error fetching employee data:', error);
            this._matSnackBar.open('Error loading employee data', 'OK', {
                verticalPosition: 'top',
                duration: 3000,
            });
        }
    }

    /**
     * Handle form submission
     *
     * @param dataForm
     */
    async onClickSubmitAttendance(dataForm): Promise<void> {

        try {
            let messageContentSuccess: string;
            let messageContentError: string;
            if (dataForm.date) {
                dataForm.date = formatDate(dataForm.date, 'yyyy-MM-dd', 'en-US');
            }

            let responseData;
            if (!this.id) {
                responseData = await this._attendanceRepository.insertAttendance(dataForm).toPromise();
                messageContentSuccess = 'Data inserted successfully';
                messageContentError = 'Error inserting data';
            } else {
                responseData = await this._attendanceRepository.updateAttendance(dataForm).toPromise();
                messageContentSuccess = 'Data updated successfully';
                messageContentError = 'Error updating data';
            }
            if (responseData.response === 'OK' || responseData.id || responseData.affected) {
                this._matSnackBar.open(messageContentSuccess, 'OK', {
                    verticalPosition: 'top',
                    duration: 3000
                });

                this.formAttendance.reset();

                if (!this.id) {
                    this._router.navigate(['apps/list-attendance']);
                }
            } else {
                this._matSnackBar.open(messageContentError, 'ERROR', {
                    verticalPosition: 'top',
                    duration: 3000
                });
            }
        } catch (error) {
            console.error('Error submitting attendance:', error);
            this._matSnackBar.open('Error submitting attendance', 'OK', {
                verticalPosition: 'top',
                duration: 3000
            });
        }
    }
}