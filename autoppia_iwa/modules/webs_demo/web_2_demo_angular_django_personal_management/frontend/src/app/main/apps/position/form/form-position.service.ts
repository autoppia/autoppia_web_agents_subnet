import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Resolve } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { PositionRepository } from '../repositories/position.repository';

@Injectable()
export class FormPositionService implements Resolve<any>
{
    routeParams: any;
    dataForm: any;
    onPositionChanged: BehaviorSubject<any>;

    /**
     * Constructor
     *
     * @param {HttpClient} _httpClient
     */
    constructor(
        private _positionRepository: PositionRepository,
    ) {
        // Set the defaults
        this.onPositionChanged = new BehaviorSubject({});
    }

    /**
     * Resolver
     *
     * @param {ActivatedRouteSnapshot} route
     * @returns {any}
     */
    async resolve(route: ActivatedRouteSnapshot) {

        if (route.params.id) {
            this.routeParams = route.params;

            const RESPONSEDATA = await this._positionRepository.getPositionById(route.params.id);

            if (RESPONSEDATA) {

                if (RESPONSEDATA[0]) {
                    this.dataForm = RESPONSEDATA[0];
                } else {
                    this.dataForm = RESPONSEDATA;
                }

                this.onPositionChanged.next(this.dataForm);
            } else {
                this.onPositionChanged.next(false);
            }
        } else {
            this.onPositionChanged.next(false);
        }

        return;

    }

}
