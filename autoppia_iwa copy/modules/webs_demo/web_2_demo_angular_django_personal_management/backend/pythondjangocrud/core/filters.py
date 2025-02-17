from enum import IntEnum

from django.db.models import Count
from rest_framework.generics import GenericAPIView

from pythondjangocrud.core.utils import camel_to_snake_object_keys


class PostFilterType(IntEnum):
    LIST_ALL = 1


class FilterFieldsMixin(GenericAPIView):
    """
    Mixin to filter queryset.
    """
    ignore_fields = ['limit', 'offset', 'ordering']
    filterset_fields = []
    text_filter_fields = []
    list_filter_fields = []
    list_all_filter_fields = []
    alias_filter_fields = {}
    paginated = True

    def filter_queryset(self, queryset):
        queryset = super(FilterFieldsMixin, self).filter_queryset(queryset)
        post_filter_checks = []
        query_params = self.get_query_params()
        filters = {}
        for field_name in query_params:
            ignore_fields = self.ignore_fields + list(self.filterset_fields)
            if field_name in ignore_fields:
                continue
            value = query_params.get(field_name, None)
            if value is None or value == '':
                continue
            if field_name in self.text_filter_fields:
                filters[field_name + '__icontains'] = value
                continue
            if field_name in self.list_filter_fields:
                filters[field_name + '__in'] = value.split(',')
                continue
            if field_name in self.list_all_filter_fields:
                post_filter_checks.append((PostFilterType.LIST_ALL, field_name, value.split(',')))
                continue
            if field_name in self.alias_filter_fields:
                filters[self.alias_filter_fields[field_name]] = value
                continue
        queryset = queryset.filter(**filters).distinct()
        for filter_type, field, value in post_filter_checks:
            if filter_type == PostFilterType.LIST_ALL:
                queryset = queryset.filter(*((field + '__in', value),))                     .annotate(count=Count(field)).filter(count=len(value))
        return queryset

    def get_query_params(self):
        return camel_to_snake_object_keys(self.request.query_params)

    def paginate_queryset(self, queryset):
        paginated = self.get_query_params().get('paginated', self.paginated)
        paginated = False if paginated == 'false' or not paginated else True
        if paginated:
            return super(FilterFieldsMixin, self).paginate_queryset(queryset)
        else:
            return None


class FilterByKwargFieldMixin:
    kwargs_fields = []

    def filter_queryset(self, queryset):
        queryset = super(FilterByKwargFieldMixin, self).filter_queryset(queryset)
        filter_fields = dict()
        for kwarg_name, filter_name in self.kwargs_fields:
            kwarg_value = self.kwargs.get(kwarg_name, None)
            if kwarg_value:
                filter_fields[filter_name] = kwarg_value
        if filter_fields:
            queryset = queryset.filter(**filter_fields)
        return queryset


class SerializerSetMixin(object):
    serializer_class = None
    min_serializer = None
    list_serializer = None
    detail_serializer = None
    create_serializer = None
    update_serializer = None

    def get_serializer_class(self):
        action = getattr(self, 'action', 'list')
        if action in ('list',):
            return self.get_list_serializer_class()
        if action in ('create',):
            return self.get_create_serializer_class()
        if action in ('update', 'partial_update'):
            return self.get_update_serializer_class()
        return self.get_detail_serializer_class()

    def get_list_serializer_class(self):
        minified = self.get_query_params().get('minified', 'false')
        if minified != 'false':
            return self.min_serializer or self.list_serializer
        return self.list_serializer or self.detail_serializer or self.serializer_class

    def get_detail_serializer_class(self):
        return self.detail_serializer or self.list_serializer or self.serializer_class

    def get_create_serializer_class(self):
        return self.create_serializer or self.update_serializer or self.get_detail_serializer_class()

    def get_update_serializer_class(self):
        return self.update_serializer or self.create_serializer or self.get_detail_serializer_class()
