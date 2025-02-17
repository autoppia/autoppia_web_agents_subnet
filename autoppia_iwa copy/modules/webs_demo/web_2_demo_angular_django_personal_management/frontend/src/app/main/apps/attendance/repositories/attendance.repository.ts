import {Injectable} from '@angular/core';
import {HttpClient, HttpHeaders} from '@angular/common/http';
import {environment} from '../../../../../environments/environment';
import {Observable} from 'rxjs';

@Injectable()
export class AttendanceRepository {

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
     * Insert attendance
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     insertAttendance(dataForm): Observable<any> {

        const dataSend = {
            employee_id: dataForm.employee_id,
            date: dataForm.date,
            status: dataForm.status,
        };

        return this._httpClient.post(this.urlBackend + '/attendance/', dataSend);
    }

    /**
     * Update attendance
     *
     * @param dataForm
     * @returns {Observable<any>}
     */
     updateAttendance(dataForm): Observable<any> {

        const dataSend = {
            employee_id: dataForm.employee_id,
            date: dataForm.date,
            status: dataForm.status,
        };

        return this._httpClient.put(this.urlBackend + '/attendance/' + dataForm.id + '/', dataSend);
    }

    /**
     * Get attendance
     *
     * @returns {Observable<any>}
     */
     getAttendance(): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/attendance/');
    }

    /**
     * Get attendance by id
     *
     * @returns {Observable<any>}
     */
    getAttendanceById(id: number): Observable<any> {
        return this._httpClient.get(this.urlBackend + '/attendance/' + id);
    }

    /**
     * Delete attendance by id
     *
     * @returns {Observable<any>}
     */
     deleteAttendanceById(id: number): Observable<any> {
        return this._httpClient.delete(this.urlBackend + '/attendance/' + id);
    }

}
