import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Resolve } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { AttendanceRepository } from '../repositories/attendance.repository';

@Injectable()
export class FormAttendanceService implements Resolve<any>
{
    routeParams: any;
    dataForm: any;
    onAttendanceChanged: BehaviorSubject<any>;

    /**
     * Constructor
     *
     * @param {HttpClient} _httpClient
     */
    constructor(
        private _attendanceRepository: AttendanceRepository,
    ) {
        // Set the defaults
        this.onAttendanceChanged = new BehaviorSubject({});
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

            const RESPONSEDATA = await this._attendanceRepository.getAttendanceById(route.params.id);

            if (RESPONSEDATA) {

                if (RESPONSEDATA[0]) {
                    this.dataForm = RESPONSEDATA[0];
                } else {
                    this.dataForm = RESPONSEDATA;
                }

                this.onAttendanceChanged.next(this.dataForm);
            } else {
                this.onAttendanceChanged.next(false);
            }
        } else {
            this.onAttendanceChanged.next(false);
        }

        return;

    }

}
