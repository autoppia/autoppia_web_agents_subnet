import {Component, OnDestroy, OnInit} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject} from 'rxjs';
import {takeUntil} from 'rxjs/operators';
import {fuseAnimations} from '@fuse/animations';
import {DepartmentRepository} from '../repositories/department.repository';
import {FormDepartmentService} from './form-department.service';
import {ActivatedRoute, Router} from '@angular/router';
@Component({
    selector: 'forms-department',
    templateUrl: './form-department.component.html',
    styleUrls: ['./form-department.component.scss'],
    animations: fuseAnimations
})
export class FormDepartmentComponent implements OnInit, OnDestroy {

    id: number;
    routeParams: any;
    formDepartment: FormGroup;

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
    private department: any;
    private pageType: string;

    /**
     * Constructor
     *
     * @param {FormBuilder} _formBuilder
     * @param _departmentRepository
     * @param _formDepartmentService
     * @param _matSnackBar
     * @param _router
     * @param _activatedRoute*
     */
    constructor(
        private _formBuilder: FormBuilder,
        private _departmentRepository: DepartmentRepository,
        private _formDepartmentService: FormDepartmentService,
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

        // Subscribe to update department on changes
        this._formDepartmentService.onDepartmentChanged
            .pipe(takeUntil(this._unsubscribeAll))
            .subscribe(department => {
                if (department.id) {
                    this.department = department;
                    this.pageType = 'edit';
                } else {
                    this.pageType = 'new';
                    this.department = false;
                }

                this.formDepartment = this.createDepartmentForm();

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
     * Create department form
     *
     * @returns {FormGroup}
     */
    createDepartmentForm(): FormGroup {
        return this._formBuilder.group({
            id: [this.department.id],
            name: [this.department.name, [Validators.required]],
            location: [this.department.location, [Validators.required]],
        });
    }

    async loadModel(): Promise<void> {
        const response = await this._departmentRepository.getDepartmentById(this.id).toPromise();
        this.formDepartment.patchValue(response);
    }

    /**
     * Receive values
     */
    async onClickSubmitDepartment(dataForm): Promise<void> {

        let responseData;

        try {

            let messajeContentSuccess: string;
            let messajeContentError: string;

            if (!this.id) {
                responseData = await this._departmentRepository.insertDepartment(dataForm).toPromise();
                messajeContentSuccess = 'Los datos fueron insertados satisfactoriamente';
                messajeContentError = 'Ocurrio un error en la inserción de los datos';

            } else {
                responseData = await this._departmentRepository.updateDepartment(dataForm).toPromise();
                messajeContentSuccess = 'Los datos fueron modificados satisfactoriamente';
                messajeContentError = 'Ocurrio un error en la modificación de los datos';
            }

            if (responseData.response === 'OK'  || responseData.id || responseData.affected) {

                this._matSnackBar.open(messajeContentSuccess, 'OK', {
                    verticalPosition: 'top',
                    duration: 3000
                });

                this.formDepartment.reset();

                if (!this.id) {
                    this._router.navigate(['apps/list-department']);
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
