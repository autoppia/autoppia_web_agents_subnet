import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Resolve } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { DepartmentRepository } from '../repositories/department.repository';

@Injectable()
export class FormDepartmentService implements Resolve<any>
{
    routeParams: any;
    dataForm: any;
    onDepartmentChanged: BehaviorSubject<any>;

    /**
     * Constructor
     *
     * @param {HttpClient} _httpClient
     */
    constructor(
        private _departmentRepository: DepartmentRepository,
    ) {
        // Set the defaults
        this.onDepartmentChanged = new BehaviorSubject({});
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

            const RESPONSEDATA = await this._departmentRepository.getDepartmentById(route.params.id);

            if (RESPONSEDATA) {

                if (RESPONSEDATA[0]) {
                    this.dataForm = RESPONSEDATA[0];
                } else {
                    this.dataForm = RESPONSEDATA;
                }

                this.onDepartmentChanged.next(this.dataForm);
            } else {
                this.onDepartmentChanged.next(false);
            }
        } else {
            this.onDepartmentChanged.next(false);
        }

        return;

    }

}
