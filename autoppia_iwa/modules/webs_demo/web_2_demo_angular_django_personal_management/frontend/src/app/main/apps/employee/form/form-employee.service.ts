import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Resolve } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { EmployeeRepository } from '../repositories/employee.repository';

@Injectable()
export class FormEmployeeService implements Resolve<any>
{
    routeParams: any;
    dataForm: any;
    onEmployeeChanged: BehaviorSubject<any>;

    /**
     * Constructor
     *
     * @param {HttpClient} _httpClient
     */
    constructor(
        private _employeeRepository: EmployeeRepository,
    ) {
        // Set the defaults
        this.onEmployeeChanged = new BehaviorSubject({});
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

            const RESPONSEDATA = await this._employeeRepository.getEmployeeById(route.params.id);

            if (RESPONSEDATA) {

                if (RESPONSEDATA[0]) {
                    this.dataForm = RESPONSEDATA[0];
                } else {
                    this.dataForm = RESPONSEDATA;
                }

                this.onEmployeeChanged.next(this.dataForm);
            } else {
                this.onEmployeeChanged.next(false);
            }
        } else {
            this.onEmployeeChanged.next(false);
        }

        return;

    }

}
