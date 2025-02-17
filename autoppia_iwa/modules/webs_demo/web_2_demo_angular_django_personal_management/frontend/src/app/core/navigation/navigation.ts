import { FuseNavigation } from '@fuse/types';

export const navigation: FuseNavigation[] = [
    {
        id: 'pages',
        title: 'Pages',
        type: 'group',
        icon: 'pages',
        children: [/*FLAGH*/
            {
                id: 'forms-payroll',
                title: 'Payroll',
                type: 'item',
                icon: 'web_asset',
                url: '/apps/list-payroll'
            },
            {
                id: 'forms-attendance',
                title: 'Attendance',
                type: 'item',
                icon: 'web_asset',
                url: '/apps/list-attendance'
            },
            {
                id: 'forms-position',
                title: 'Position',
                type: 'item',
                icon: 'web_asset',
                url: '/apps/list-position'
            },
            {
                id: 'forms-department',
                title: 'Department',
                type: 'item',
                icon: 'web_asset',
                url: '/apps/list-department'
            },
            {
                id: 'forms-employee',
                title: 'Employee',
                type: 'item',
                icon: 'web_asset',
                url: '/apps/list-employee'
            },
        ]
    }
];
