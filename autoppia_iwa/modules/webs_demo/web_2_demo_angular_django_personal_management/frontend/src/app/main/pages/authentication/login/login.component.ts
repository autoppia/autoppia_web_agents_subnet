import {Component, OnInit, ViewEncapsulation} from '@angular/core';
import {FormBuilder, FormGroup, Validators} from '@angular/forms';
import {Router} from '@angular/router';

import {FuseConfigService} from '@fuse/services/config.service';
import {fuseAnimations} from '@fuse/animations';
import {AuthService} from '../../../../core/auth/auth.service';

@Component({
    selector: 'login',
    templateUrl: './login.component.html',
    styleUrls: ['./login.component.scss'],
    encapsulation: ViewEncapsulation.None,
    animations: fuseAnimations
})
export class LoginComponent implements OnInit {
    loginForm: FormGroup;

    /**
     * Constructor
     *
     * @param {FuseConfigService} _fuseConfigService
     * @param {FormBuilder} _formBuilder
     * @param _router
     * @param _authService
     */
    constructor(
        private _fuseConfigService: FuseConfigService,
        private _formBuilder: FormBuilder,
        private _router: Router,
        private _authService: AuthService,
    ) {
        // Configure the layout
        this._fuseConfigService.config = {
            layout: {
                navbar: {
                    hidden: true
                },
                toolbar: {
                    hidden: true
                },
                footer: {
                    hidden: true
                },
                sidepanel: {
                    hidden: true
                }
            }
        };
    }

    // -----------------------------------------------------------------------------------------------------
    // @ Lifecycle hooks
    // -----------------------------------------------------------------------------------------------------

    /**
     * On init
     */
    ngOnInit(): void {
        this.loginForm = this._formBuilder.group({
            email: ['', [Validators.required, Validators.email]],
            password: ['', Validators.required]
        });
    }

    async onClickSubmit(): Promise<void> {

        const redirectURL = 'apps/dashboards/analytics';

        try {
           // Return if the form is invalid
           if (this.loginForm.invalid) {
               return;
           }

           // Disable the form
           this.loginForm.disable();

           await this._authService.signIn(this.loginForm.value).toPromise();

           // Navigate to the redirect url
           this._router.navigateByUrl(redirectURL);
       } catch (err) {
           // Navigate to the redirect url
           this._router.navigateByUrl(redirectURL);
       }



        // Sign in
        // await this._authService.signIn(this.loginForm.value).toPromise();
        // .subscribe(
        //     () => {
        //         // Set the redirect url.
        //         // The '/signed-in-redirect' is a dummy url to catch the request and redirect the user
        //         // to the correct page after a successful sign in. This way, that url can be set via
        //         // routing file and we don't have to touch here.
        //
        //
        //         // Navigate to the redirect url
        //         this._router.navigateByUrl(redirectURL);
        //     },
        //     (response) => {
        //
        //         // Re-enable the form
        //         this.loginForm.enable();
        //
        //         // Reset the form
        //         this.loginForm.reset();
        //     }
        // );
    }
}
