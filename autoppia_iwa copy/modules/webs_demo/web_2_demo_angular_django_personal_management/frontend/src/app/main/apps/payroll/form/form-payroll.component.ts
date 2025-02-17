import {Component, OnDestroy, OnInit} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject} from 'rxjs';
import {takeUntil} from 'rxjs/operators';
import {fuseAnimations} from '@fuse/animations';
import {PayrollRepository} from '../repositories/payroll.repository';
import {FormPayrollService} from './form-payroll.service';
import {ActivatedRoute, Router} from '@angular/router';
import {EmployeeRepository} from '../../employee/repositories/employee.repository';
import {formatDate} from '@angular/common';

@Component({
    selector: 'forms-payroll',
    templateUrl: './form-payroll.component.html',
    styleUrls: ['./form-payroll.component.scss'],
    animations: fuseAnimations
})
export class FormPayrollComponent implements OnInit, OnDestroy {

    id: number;
    routeParams: any;
    formPayroll: FormGroup;
    loading: boolean = false; // Add a loading state


    // Horizontal Stepper
    horizontalStepperStep1: FormGroup;
    horizontalStepperStep2: FormGroup;
    horizontalStepperStep3: FormGroup;

    // Vertical Stepper
    verticalStepperStep1: FormGroup;
    verticalStepperStep2: FormGroup;
    verticalStepperStep3: FormGroup;
    dataEmployeeSelect: any;

    // Private
    private _unsubscribeAll: Subject<any>;
    private payroll: any;
    private pageType: string;

    /**
     * Constructor
     *
     * @param {FormBuilder} _formBuilder
     * @param _payrollRepository
     * @param _formPayrollService
     * @param _matSnackBar
     * @param _router
     * @param _activatedRoute*
     */
    constructor(
        private _formBuilder: FormBuilder,
        private _payrollRepository: PayrollRepository,
        private _formPayrollService: FormPayrollService,
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
                    this.id = +params.id;
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

        // Subscribe to update payroll on changes
        this._formPayrollService.onPayrollChanged
            .pipe(takeUntil(this._unsubscribeAll))
            .subscribe(payroll => {
                this.payroll = payroll;
                this.pageType = payroll?.id ? 'edit' : 'new';
                this.formPayroll = this.createPayrollForm();
            });

        // Load employee data
        this.loading = true;
        try {
            const response = await this._employeeRepository.getEmployee().toPromise();
            this.dataEmployeeSelect = response?.results || []; // Ensure this is an array
        } catch (error) {
            console.error('Error loading employee data:', error);
            this.showSnackbar('Failed to load employee data', 'ERROR');
        } finally {
            this.loading = false;
        }
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
     * Create payroll form
     *
     * @returns {FormGroup}
     */
    createPayrollForm(): FormGroup {
        return this._formBuilder.group({
            id: [this.payroll?.id || null],
            employee_id: [this.payroll?.employee_id || null, [Validators.required]],
            pay_date: [this.payroll?.pay_date || null, [Validators.required]],
            amount: [this.payroll?.amount || null, [Validators.required]],
        });
    }

    async loadModel(): Promise<void> {
        this.loading = true;
        try {
            const response = await this._payrollRepository.getPayrollById(this.id).toPromise();
            this.formPayroll.patchValue(response);
        } catch (error) {
            console.error('Error loading payroll data:', error);
            this.showSnackbar('Failed to load payroll data', 'ERROR');
        } finally {
            this.loading = false;
        }
    }

    /**
     * Handle form submission
     */
    async onClickSubmitPayroll(dataForm: any): Promise<void> {
        this.loading = true;
        try {
            let responseData;
            let messageSuccess: string;
            let messageError: string;
            if (dataForm.pay_date) {
                dataForm.pay_date = formatDate(dataForm.pay_date, 'yyyy-MM-dd', 'en-US');
            }
            if (!this.id) {
                responseData = await this._payrollRepository.insertPayroll(dataForm).toPromise();
                messageSuccess = 'Los datos fueron insertados satisfactoriamente';
                messageError = 'Ocurrio un error en la inserción de los datos';
            } else {
                responseData = await this._payrollRepository.updatePayroll(dataForm).toPromise();
                messageSuccess = 'Los datos fueron modificados satisfactoriamente';
                messageError = 'Ocurrio un error en la modificación de los datos';
            }

            if (responseData?.response === 'OK' || responseData?.id || responseData?.affected) {
                this.showSnackbar(messageSuccess, 'OK');
                this.formPayroll.reset();

                if (!this.id) {
                    this._router.navigate(['apps/list-payroll']);
                }
            } else {
                this.showSnackbar(messageError, 'ERROR');
            }
        } catch (error) {
            console.error('Error submitting payroll:', error);
            if (error.error?.payDate) {
                this.showSnackbar(`Error: ${error.error.payDate[0]}`, 'ERROR');
            } else {
                this.showSnackbar('Failed to submit payroll data', 'ERROR');
            }
        } finally {
            this.loading = false;
        }
    }

    // -----------------------------------------------------------------------------------------------------
    // @ Private methods
    // -----------------------------------------------------------------------------------------------------

    /**
     * Show a snackbar notification
     */
    private showSnackbar(message: string, action: string): void {
        this._matSnackBar.open(message, action, {
            verticalPosition: 'top',
            duration: 3000
        });
    }
}