import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders} from '@angular/common/http';
import {environment} from '../../../../../environments/environment';
import {Observable} from 'rxjs';

@Injectable()
export class PayrollRepository {

    urlBackend: string = environment.urlBackend;

    /**
     * Constructor
     *
     * @param {HttpClient} _httpClient
     */
    constructor(
        private _httpClient: HttpClient,
    ) {
    }

    /**
     * Insert payroll
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     insertPayroll(dataForm): Observable<any> {

        const dataSend = {
            employee_id: dataForm.employee_id,
            pay_date: dataForm.pay_date,
            amount: dataForm.amount,
        };

        return this._httpClient.post(this.urlBackend + '/payroll/', dataSend);
    }

    /**
     * Update payroll
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     updatePayroll(dataForm): Observable<any> {

        const dataSend = {
            employee_id: dataForm.employee_id,
            pay_date: dataForm.pay_date,
            amount: dataForm.amount,
        };

        return this._httpClient.put(this.urlBackend + '/payroll/' + dataForm.id + '/', dataSend);
    }

    /**
     * Get payroll
     *
     * @returns {Observable<any>}
     */
     getPayroll(): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/payroll/');
    }

    /**
     * Get payroll by id
     *
     * @returns {Observable<any>}
     */
    getPayrollById(id: number): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/payroll/' + id);
    }

    /**
     * Delete payroll by id
     *
     * @returns {Observable<any>}
     */
     deletePayrollById(id: number): Observable<any> {
        return this._httpClient.delete(this.urlBackend + '/payroll/' + id);
    }

}
