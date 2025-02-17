import {Component, OnDestroy, OnInit} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {MatSnackBar} from '@angular/material/snack-bar';
import {Subject} from 'rxjs';
import {takeUntil} from 'rxjs/operators';
import {fuseAnimations} from '@fuse/animations';
import {PositionRepository} from '../repositories/position.repository';
import {FormPositionService} from './form-position.service';
import {ActivatedRoute, Router} from '@angular/router';
@Component({
    selector: 'forms-position',
    templateUrl: './form-position.component.html',
    styleUrls: ['./form-position.component.scss'],
    animations: fuseAnimations
})
export class FormPositionComponent implements OnInit, OnDestroy {

    id: number;
    routeParams: any;
    formPosition: FormGroup;

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
    private position: any;
    private pageType: string;

    /**
     * Constructor
     *
     * @param {FormBuilder} _formBuilder
     * @param _positionRepository
     * @param _formPositionService
     * @param _matSnackBar
     * @param _router
     * @param _activatedRoute*
     */
    constructor(
        private _formBuilder: FormBuilder,
        private _positionRepository: PositionRepository,
        private _formPositionService: FormPositionService,
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

        // Subscribe to update position on changes
        this._formPositionService.onPositionChanged
            .pipe(takeUntil(this._unsubscribeAll))
            .subscribe(position => {
                if (position.id) {
                    this.position = position;
                    this.pageType = 'edit';
                } else {
                    this.pageType = 'new';
                    this.position = false;
                }

                this.formPosition = this.createPositionForm();

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
     * Create position form
     *
     * @returns {FormGroup}
     */
    createPositionForm(): FormGroup {
        return this._formBuilder.group({
            id: [this.position.id],
            title: [this.position.title, [Validators.required]],
            salary: [this.position.salary, [Validators.required]],
        });
    }

    async loadModel(): Promise<void> {
        const response = await this._positionRepository.getPositionById(this.id).toPromise();
        this.formPosition.patchValue(response);
    }

    /**
     * Receive values
     */
    async onClickSubmitPosition(dataForm): Promise<void> {

        let responseData;

        try {

            let messajeContentSuccess: string;
            let messajeContentError: string;

            if (!this.id) {
                responseData = await this._positionRepository.insertPosition(dataForm).toPromise();
                messajeContentSuccess = 'Los datos fueron insertados satisfactoriamente';
                messajeContentError = 'Ocurrio un error en la inserción de los datos';

            } else {
                responseData = await this._positionRepository.updatePosition(dataForm).toPromise();
                messajeContentSuccess = 'Los datos fueron modificados satisfactoriamente';
                messajeContentError = 'Ocurrio un error en la modificación de los datos';
            }

            if (responseData.response === 'OK'  || responseData.id || responseData.affected) {

                this._matSnackBar.open(messajeContentSuccess, 'OK', {
                    verticalPosition: 'top',
                    duration: 3000
                });

                this.formPosition.reset();

                if (!this.id) {
                    this._router.navigate(['apps/list-position']);
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
