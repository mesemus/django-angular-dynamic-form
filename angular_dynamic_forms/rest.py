# noinspection PyUnresolvedReferences
import functools
import inspect
import os
import re

from django.core.exceptions import FieldDoesNotExist
from django.db.models import TextField
from django.http import Http404
from django.utils.translation import gettext
from rest_framework import renderers
from rest_framework.decorators import action
from rest_framework.response import Response


class AngularFormMixin(object):
    """
        A viewset mixin that provides django.forms like interface for user interfaces built upon django rest framework.
        The mixin registers four routes - two on lists and two on details. They are:

           1 /form
           2 /form/<form_id>
           3 /<id>/form
           4 /<id>/form/<form_id>

        Cases #1, #3 are for cases where there is just a single form definition for a given viewset, #2, #4 enable
        usage of multiple forms on a single formset (for example, "simple" and "detail" projections, see the demos
        for details).

        All the fields below are not required. If they are not used, the fields and their mapping to HTML controls
        is taken from the viewset's serializer.
    """

    """
        The layout of the form - a list of form element definitions. Each definition might be:

           * a name of the field (string) - the field with its defaults will be filled with definition 
             from the serializer
           * dictionary containing "type" field and in many cases "id" field. The list of supported types
             can be found at https://github.com/mesemus/django-angular-dynamic-forms/blob/develop/angular/src/impl/django-form-iface.ts
           * a call to AngularFormMixin.columns(...) or AngularFormMixin.fieldset(...) - see the All controls and layout
             demo for details
    """
    form_layout = None

    """
        Overrides the title of the form, if left empty an autogenerated title is used
    """
    form_title = None

    """
        A map of id => dict of any field defaults. The defaults will be used to override the values taken from the 
        associated serializer.
        See https://github.com/mesemus/django-angular-dynamic-forms/blob/develop/angular/src/impl/django-form-iface.ts
        for a list of recognized items.
    """
    form_defaults = {}

    """
    These three is a map from form_id => layout, title, map of defaults for the case of multiple forms per viewset
    """
    form_layouts  = {}
    form_titles   = {}
    form_defaults_map = {}

    """
    A map of linked forms, i.e. forms defined on other viewsets linked by foreign key or m2m. See @linked_forms
    decorator and linked_form(...) call for details. 
    """
    linked_forms = {}

    @staticmethod
    def fieldset(title, controls):
        """
        Returns a record for a fieldset - ie. multiple fields grouped together with a title

        :param title:       the title of the fieldset
        :param controls:    a list of controls
        :return:            fieldset record
        """
        return {
            'type': 'fieldset',
            'label': title,
            'controls': controls
        }

    @staticmethod
    def columns(*controls):
        """
        Returns the fields organized to columns, implicitly of the same width, can be changed in scss

        :param controls:    the list of controls that will be placed to columns. If you need to place
                            more controls into a single column, use either a simple array containing
                            the components or .group(*controls) method
        :return:            record for a multiple columns layout
        """
        return {
            'type': 'columns',
            'columns': controls
        }

    @staticmethod
    def group(*controls):
        """
        Groups the fields into a group. Within the group, fields are layed out vertically.

        :param controls:    the list of controls that will be grouped together.
        :return:            record for a group
        """
        return controls


    # noinspection PyUnusedLocal
    @action(detail=True, renderer_classes=[renderers.JSONRenderer], url_path='form')
    def form(self, request, *args, **kwargs):
        return Response(self._get_form_metadata(has_instance=True,
                                                base_path=self._base_path(request.path)))

    # noinspection PyUnusedLocal
    @action(detail=False, renderer_classes=[renderers.JSONRenderer], url_path='form')
    def form_list(self, request, *args, **kwargs):
        return Response(self._get_form_metadata(has_instance=False,
                                                base_path=self._base_path(request.path)))

    # noinspection PyUnusedLocal
    @action(detail=True, renderer_classes=[renderers.JSONRenderer], url_path='form/(?P<form_name>.+)')
    def form_with_name(self, request, *args, form_name=None, **kwargs):
        return Response(self._get_form_metadata(has_instance=True, form_name =form_name or '',
                                                base_path=self._base_path(request.path, 2)))

    # noinspection PyUnusedLocal
    @action(detail=False, renderer_classes=[renderers.JSONRenderer], url_path='form/(?P<form_name>.+)')
    def form_list_with_name(self, request, *args, form_name=None, **kwargs):
        return Response(self._get_form_metadata(has_instance=False, form_name =form_name or '',
                                                base_path=self._base_path(request.path, 2)))

    @staticmethod
    def _base_path(path, level=1):
        if path.endswith('/'):
            path = path[:-1]
        for _lev in range(level):
            path = os.path.dirname(path)
        return path + '/'
    #
    # the rest of the methods on this class are private ones
    #

    def _get_form_layout(self, fields, form_name):
        if form_name:
            form_layout = self.form_layouts[form_name]
            form_defaults = self.form_defaults_map.get(form_name, None)
        else:
            form_layout = self.form_layout
            form_defaults = self.form_defaults

        if not form_defaults:
            form_defaults = {}

        if callable(form_defaults):
            form_defaults = form_defaults(fields)

        if form_layout:
            if callable(form_layout):
                layout = form_layout(fields)
            else:
                layout = form_layout
        else:
            # no layout, generate from fields
            layout = [self._get_field_layout(field_name, fields[field_name])
                        for field_name in fields if not fields[field_name]['read_only']]

        layout = self._transform_layout(layout, form_defaults, wrap_array=False)

        return layout

    def _convert_camel_case(self, x):
        if isinstance(x, dict):
            for k, v in list(x.items()):
                self._convert_camel_case(v)
                camel_k = camel(k)
                if camel_k != k:
                    del x[k]
                    x[camel_k] = v
        if isinstance(x, tuple) or isinstance(x, list):
            for v in x:
                self._convert_camel_case(v)
        return x

    def _get_field_layout(self, field_name, field):
        return {'id': field_name}

    # @LoggerDecorator.log()
    def _transform_layout(self, layout, form_defaults, wrap_array=True):

        if isinstance(layout, dict):
            layout = layout.copy()

            if 'id' in layout and layout['id'] in form_defaults:
                layout.update(form_defaults[layout['id']])

            for (k, v) in list(layout.items()):
                if callable(v):
                    layout[k] = v(self)

            layout_type = layout.get('type', 'string')

            if layout_type in ('fieldset', 'group'):
                layout['controls'] = self._transform_layout(layout['controls'], form_defaults, wrap_array=False)
                return layout

            if layout_type == 'columns':
                layout['controls'] = self._transform_layout(layout['columns'], form_defaults, wrap_array=False)
                del layout['columns']
                return layout

            if layout_type == 'string':
                # string or textarea?
                qs = self.get_queryset()
                model = qs.model
                if model:
                    try:
                        field = model._meta.get_field(layout['id'])
                        if isinstance(field, TextField):
                            layout['type'] = 'textarea'
                    except FieldDoesNotExist:
                        pass
            return layout

        if isinstance(layout, list) or isinstance(layout, tuple):
            # otherwise it is a group of controls
            if wrap_array:
                return {
                    'type': 'group',
                    'controls': [self._transform_layout(l, form_defaults) for l in layout]
                }
            else:
                return [self._transform_layout(l, form_defaults) for l in layout]

        if isinstance(layout, str):
            return self._transform_layout({
                'id': layout
            }, form_defaults)

        raise NotImplementedError('Layout "%s" not implemented' % layout)

    def _get_form_title(self, has_instance, serializer, form_name):
        form_title = self.form_title
        if form_name and self.form_titles:
            form_title = self.form_titles.get(form_name, None)

        if form_title:
            return self.form_title['edit' if has_instance else 'create']

        # noinspection PyProtectedMember
        name = serializer.Meta.model._meta.verbose_name
        if has_instance:
            name = gettext('Editing %s') % name
        else:
            name = gettext('Creating a new %s') % name

        return name

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def _get_actions(self, has_instance, serializer):
        if has_instance:
            return [
                {
                    'id': 'save',
                    'color': 'primary',
                    'label': gettext('Save')
                },
                {
                    'id': 'cancel',
                    'label': gettext('Cancel'),
                    'cancel': True
                },
            ]
        else:
            return [
                {
                    'id': 'create',
                    'color': 'primary',
                    'label': gettext('Create')
                },
                {
                    'id': 'cancel',
                    'label': gettext('Cancel'),
                    'cancel': True
                },
            ]

    def _get_form_metadata(self, has_instance, form_name='', base_path=None):

        if form_name:

            if form_name in self.linked_forms:
                return self._linked_form_metadata(form_name)

            if not self.form_layouts:
                raise Http404('Form layouts not configured. '
                                            'Please add form_layouts attribute on the viewset class')

            if form_name not in self.form_layouts:
                raise Http404('Form with name %s not found' % form_name)

        ret = {}

        # noinspection PyUnresolvedReferences
        serializer = self.get_serializer()

        # noinspection PyUnresolvedReferences
        metadata_class = self.metadata_class()

        fields_info = metadata_class.get_serializer_info(serializer=serializer)
        layout = self._get_form_layout(fields_info, form_name)
        layout = self._decorate_layout(layout, fields_info)

        ret['layout'] = self._convert_camel_case(layout)

        ret['formTitle'] = self._get_form_title(has_instance, serializer, form_name)

        ret['actions'] = self._get_actions(has_instance, serializer)

        ret['method'] = 'patch' if has_instance else 'post'
        ret['hasInitialData'] = has_instance
        ret['djangoUrl'] = base_path + self._get_url_by_form_id(form_name)

        # print(json.dumps(ret, indent=4))
        return ret

    @functools.lru_cache(maxsize=16)
    def _get_url_by_form_id(self, form_id):
        if not form_id:
            return ''
        method = inspect.getmembers(self, lambda fld: callable(fld) and getattr(fld, 'angular_form_id', None) == form_id)
        if not method:
            return ''
        ret = method[0][1].url_path
        if not ret.endswith('/'):
            ret += '/'
        return ret

    def _linked_form_metadata(self, form_name):
        request = self.request

        form_def = self.linked_forms[form_name]
        viewset = form_def['viewset']()
        viewset.request = request
        viewset.format_kwarg = self.format_kwarg

        if 'link_id' in form_def:
            link_id = request.GET.get(form_def['link_id']) or request.data.get(form_def['link_id'])
        else:
            link_id = None


        path = request.path
        # must be called from /form/ ...
        path = re.sub(r'/form(/[^/]+)?/?$', '', path)
        path = '%s/%s/' % (path, form_name)

        ret = viewset._get_form_metadata(link_id, form_name=form_def['form_id'], base_path=path)

        return ret

    # @LoggerDecorator.log()
    def _decorate_layout(self, layout, fields_info):
        if isinstance(layout, list):
            ret = []
            for it in layout:
                ret.append(self._decorate_layout(it, fields_info))
            return ret
        elif isinstance(layout, dict):
            if layout.get('type', None) in ('fieldset', 'columns', 'group'):
                layout = dict(layout)
                layout['controls'] = self._decorate_layout(layout['controls'], fields_info)
                self._decorate_layout_item(layout)
                return layout
            else:
                md = dict(fields_info.get(layout['id'], {}))
                md.update(layout)
                if md['type'] == 'choice':
                    md['type'] = 'select'
                if md.get('choices'):
                    md['choices'] = [
                        {
                            'label': x.get('label', None) or x.get('display_name', None),
                            'value': x['value']
                        } for x in md['choices']
                    ]
                self._decorate_layout_item(md)
                return md

    def _decorate_layout_item(self, item):
        pass


# privates
def camel(snake_str):
    if '_' not in snake_str:
        return snake_str
    first, *others = snake_str.split('_')
    return ''.join([first.lower(), *map(str.title, others)])


