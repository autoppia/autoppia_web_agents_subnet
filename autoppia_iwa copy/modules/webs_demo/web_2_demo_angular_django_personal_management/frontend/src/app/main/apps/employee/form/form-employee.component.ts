import {Component, OnDestroy, OnInit} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject} from 'rxjs';
import {takeUntil} from 'rxjs/operators';
import {formatDate} from '@angular/common';
import {fuseAnimations} from '@fuse/animations';
import {EmployeeRepository} from '../repositories/employee.repository';
import {FormEmployeeService} from './form-employee.service';
import {ActivatedRoute, Router} from '@angular/router';

@Component({
    selector: 'forms-employee',
    templateUrl: './form-employee.component.html',
    styleUrls: ['./form-employee.component.scss'],
    animations: fuseAnimations
})
export class FormEmployeeComponent implements OnInit, OnDestroy {

    id: number;
    routeParams: any;
    formEmployee: FormGroup;

    // Horizontal Stepper
    horizontalStepperStep1: FormGroup;
    horizontalStepperStep2: FormGroup;
    horizontalStepperStep3: FormGroup;

    // Vertical Stepper
    verticalStepperStep1: FormGroup;
    verticalStepperStep2: FormGroup;
    verticalStepperStep3: FormGroup;

    // Private
    private _unsubscribeAll: Subject<any>;
    private employee: any;
    private pageType: string;

    /**
     * Constructor
     *
     * @param {FormBuilder} _formBuilder
     * @param _employeeRepository
     * @param _formEmployeeService
     * @param _matSnackBar
     * @param _router
     * @param _activatedRoute*
     */
    constructor(
        private _formBuilder: FormBuilder,
        private _employeeRepository: EmployeeRepository,
        private _formEmployeeService: FormEmployeeService,
        private _matSnackBar: MatSnackBar,
        private _router: Router,
        private _activatedRoute: ActivatedRoute,
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
    ngOnInit(): void {

        // Subscribe to update employee on changes
        this._formEmployeeService.onEmployeeChanged
            .pipe(takeUntil(this._unsubscribeAll))
            .subscribe(employee => {
                if (employee.id) {
                    this.employee = employee;
                    this.pageType = 'edit';
                } else {
                    this.pageType = 'new';
                    this.employee = false;
                }

                this.formEmployee = this.createEmployeeForm();

            });

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
     * Create employee form
     *
     * @returns {FormGroup}
     */
    createEmployeeForm(): FormGroup {
        return this._formBuilder.group({
            id: [this.employee.id],
            first_name: [this.employee.first_name, [Validators.required]],
            last_name: [this.employee.last_name, [Validators.required]],
            email: [this.employee.email, [Validators.required]],
            hire_date: [this.employee.hire_date, [Validators.required]],
        });
    }

    async loadModel(): Promise<void> {
        const response = await this._employeeRepository.getEmployeeById(this.id).toPromise();
        this.formEmployee.patchValue(response);
    }

    /**
     * Receive values
     */
    async onClickSubmitEmployee(dataForm): Promise<void> {
        try {
            // Format hire_date to YYYY-MM-DD
            if (dataForm.hire_date) {
                dataForm.hire_date = formatDate(dataForm.hire_date, 'yyyy-MM-dd', 'en-US');
            }

            let responseData;
            let messajeContentSuccess: string;
            let messajeContentError: string;

            if (!this.id) {
                responseData = await this._employeeRepository.insertEmployee(dataForm).toPromise();
                messajeContentSuccess = 'Los datos fueron insertados satisfactoriamente';
                messajeContentError = 'Ocurrio un error en la inserción de los datos';

            } else {
                responseData = await this._employeeRepository.updateEmployee(dataForm).toPromise();
                messajeContentSuccess = 'Los datos fueron modificados satisfactoriamente';
                messajeContentError = 'Ocurrio un error en la modificación de los datos';
            }

            if (responseData.response === 'OK' || responseData.id || responseData.affected) {

                this._matSnackBar.open(messajeContentSuccess, 'OK', {
                    verticalPosition: 'top',
                    duration: 3000
                });

                this.formEmployee.reset();

                if (!this.id) {
                    this._router.navigate(['apps/list-employee']);
                }

            } else {

                this._matSnackBar.open(messajeContentError, 'ERROR', {
                    verticalPosition: 'top',
                    duration: 3000
                });
            }

        } catch (error) {
            Promise.reject(error);
        }

    }

}
