import { NgModule } from '@angular/core';

import { LoginModule } from 'app/main/pages/authentication/login/login.module';

@NgModule({
    imports: [
        // Authentication
        LoginModule,
    ]
})
export class PagesModule
{

}
