import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders} from '@angular/common/http';
import {environment} from '../../../../../environments/environment';
import {Observable} from 'rxjs';

@Injectable()
export class DepartmentRepository {

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
     * Insert department
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     insertDepartment(dataForm): Observable<any> {

        const dataSend = {
            name: dataForm.name,
            location: dataForm.location,
        };

        return this._httpClient.post(this.urlBackend + '/department/', dataSend);
    }

    /**
     * Update department
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     updateDepartment(dataForm): Observable<any> {

        const dataSend = {
            name: dataForm.name,
            location: dataForm.location,
        };

        return this._httpClient.put(this.urlBackend + '/department/' + dataForm.id + '/', dataSend);
    }

    /**
     * Get department
     *
     * @returns {Observable<any>}
     */
     getDepartment(): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/department/');
    }

    /**
     * Get department by id
     *
     * @returns {Observable<any>}
     */
    getDepartmentById(id: number): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/department/' + id);
    }

    /**
     * Delete department by id
     *
     * @returns {Observable<any>}
     */
     deleteDepartmentById(id: number): Observable<any> {
        return this._httpClient.delete(this.urlBackend + '/department/' + id);
    }

}
