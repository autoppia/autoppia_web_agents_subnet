from django.contrib import admin

class AbstractChoiceAdmin(admin.ModelAdmin):
    """
    Admin options for AbstractChoice abstract model.
    """
    list_display = ['id', 'name', 'code']


class AuditAdminMixin:
    ordering = ['pk']

    def get_merge_fields(self, origin_fields, fields):
        fields = list(fields)
        for field in origin_fields:
            if field not in fields:
                fields.append(field)
        return fields

    def get_all_fields(self, fields):
        audit_fields = ['is_active', 'creation_date', 'created_by', 'update_date', 'update_by']
        return self.get_merge_fields(origin_fields=audit_fields, fields=fields)

    def get_all_readonly_fields(self, fields):
        audit_readonly_fields = ['creation_date', 'created_by', 'update_date', 'update_by']
        return self.get_merge_fields(origin_fields=audit_readonly_fields, fields=fields)

    def get_fields(self, request, obj=None):
        fields = super(AuditAdminMixin, self).get_fields(request, obj)
        return self.get_all_fields(fields=fields)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super(AuditAdminMixin, self).get_readonly_fields(request, obj=None)
        return self.get_all_readonly_fields(fields=readonly_fields)
