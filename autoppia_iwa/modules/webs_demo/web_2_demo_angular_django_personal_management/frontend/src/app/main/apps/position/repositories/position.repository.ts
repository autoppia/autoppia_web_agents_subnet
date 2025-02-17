import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders} from '@angular/common/http';
import {environment} from '../../../../../environments/environment';
import {Observable} from 'rxjs';

@Injectable()
export class PositionRepository {

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
     * Insert position
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     insertPosition(dataForm): Observable<any> {

        const dataSend = {
            title: dataForm.title,
            salary: dataForm.salary,
        };

        return this._httpClient.post(this.urlBackend + '/position/', dataSend);
    }

    /**
     * Update position
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     updatePosition(dataForm): Observable<any> {

        const dataSend = {
            title: dataForm.title,
            salary: dataForm.salary,
        };

        return this._httpClient.put(this.urlBackend + '/position/' + dataForm.id + '/', dataSend);
    }

    /**
     * Get position
     *
     * @returns {Observable<any>}
     */
     getPosition(): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/position/');
    }

    /**
     * Get position by id
     *
     * @returns {Observable<any>}
     */
    getPositionById(id: number): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/position/' + id);
    }

    /**
     * Delete position by id
     *
     * @returns {Observable<any>}
     */
     deletePositionById(id: number): Observable<any> {
        return this._httpClient.delete(this.urlBackend + '/position/' + id);
    }

}
