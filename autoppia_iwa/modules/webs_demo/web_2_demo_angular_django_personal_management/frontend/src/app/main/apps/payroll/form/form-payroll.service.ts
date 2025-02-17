import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Resolve } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { PayrollRepository } from '../repositories/payroll.repository';

@Injectable()
export class FormPayrollService implements Resolve<any>
{
    routeParams: any;
    dataForm: any;
    onPayrollChanged: BehaviorSubject<any>;

    /**
     * Constructor
     *
     * @param {HttpClient} _httpClient
     */
    constructor(
        private _payrollRepository: PayrollRepository,
    ) {
        // Set the defaults
        this.onPayrollChanged = new BehaviorSubject({});
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

            const RESPONSEDATA = await this._payrollRepository.getPayrollById(route.params.id);

            if (RESPONSEDATA) {

                if (RESPONSEDATA[0]) {
                    this.dataForm = RESPONSEDATA[0];
                } else {
                    this.dataForm = RESPONSEDATA;
                }

                this.onPayrollChanged.next(this.dataForm);
            } else {
                this.onPayrollChanged.next(false);
            }
        } else {
            this.onPayrollChanged.next(false);
        }

        return;

    }

}
