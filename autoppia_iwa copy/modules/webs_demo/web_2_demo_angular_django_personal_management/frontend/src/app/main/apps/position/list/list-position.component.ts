import {Component, OnDestroy, OnInit} from '@angular/core';
import {Observable, Subject} from 'rxjs';
import {fuseAnimations} from '@fuse/animations';
import {MatSnackBar} from '@angular/material/snack-bar';
import {MatDialog, MatDialogRef} from '@angular/material/dialog';
import {FuseConfirmDialogComponent} from '@fuse/components/confirm-dialog/confirm-dialog.component';
import {PositionRepository} from '../repositories/position.repository';

@Component({
    selector: 'list-position',
    templateUrl: './list-position.component.html',
    styleUrls: ['./list-position.component.scss'],
    animations: fuseAnimations
})
export class ListPositionComponent implements OnInit, OnDestroy {
    rows;
    loadingIndicator: boolean;
    reorderable: boolean;
    confirmDialogRef: MatDialogRef<FuseConfirmDialogComponent>;

    // Private
    private _unsubscribeAll: Subject<any>;

    /**
     * Constructor
     *
     * @param _positionRepository
     * @param _matDialog
     * @param _matSnackBar
     */
    constructor(
        private _positionRepository: PositionRepository,
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
        this.getListPosition();
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

    async getListPosition(): Promise<any> {

        try {
            this.rows = await this._positionRepository.getPosition().toPromise();
            this.rows = this.rows.results
            console.log(this.rows);
            
            
        } catch (error) {
            throw new Error('Error: ' + error);
        }
    }

    deletePosition(id): void {

        try {
            this.confirmDialogRef = this._matDialog.open(FuseConfirmDialogComponent, {
                disableClose: false
            });

            this.confirmDialogRef.componentInstance.confirmMessage = '¿Seguro quieres eliminar el registro?';

            this.confirmDialogRef.afterClosed().subscribe(async result => {
                if (result) {
                    const responseData = await this._positionRepository.deletePositionById(id).toPromise();
                    if (responseData?.response === 'OK' || responseData?.affected) {

                        setTimeout(() => {
                            this.getListPosition();
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

    async updatePosition(id): Promise<any> {
        try {
            this.rows = await this._positionRepository.getPositionById(id).toPromise();
            this.loadingIndicator = false;
        } catch (err) {
            this.loadingIndicator = false;
            throw new Error('Error: ' + err);
        }
    }
}
