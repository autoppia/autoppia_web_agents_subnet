import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders} from '@angular/common/http';
import {environment} from '../../../../../environments/environment';
import {Observable} from 'rxjs';

@Injectable()
export class EmployeeRepository {

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
     * Insert employee
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     insertEmployee(dataForm): Observable<any> {

        const dataSend = {
            first_name: dataForm.first_name,
            last_name: dataForm.last_name,
            email: dataForm.email,
            hire_date: dataForm.hire_date,
        };

        return this._httpClient.post(this.urlBackend + '/employee/', dataSend);
    }

    /**
     * Update employee
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     updateEmployee(dataForm): Observable<any> {

        const dataSend = {
            first_name: dataForm.first_name,
            last_name: dataForm.last_name,
            email: dataForm.email,
            hire_date: dataForm.hire_date,
        };

        return this._httpClient.put(this.urlBackend + '/employee/' + dataForm.id + '/', dataSend);
    }

    /**
     * Get employee
     *
     * @returns {Observable<any>}
     */
     getEmployee(): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/employee/');
    }

    /**
     * Get employee by id
     *
     * @returns {Observable<any>}
     */
    getEmployeeById(id: number): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/employee/' + id);
    }

    /**
     * Delete employee by id
     *
     * @returns {Observable<any>}
     */
     deleteEmployeeById(id: number): Observable<any> {
        return this._httpClient.delete(this.urlBackend + '/employee/' + id);
    }

}
